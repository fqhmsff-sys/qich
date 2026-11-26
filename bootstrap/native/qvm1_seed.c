#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <json-c/json.h>
#include <limits.h>
#include <openssl/bn.h>
#include <openssl/sha.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define MAX_BYTECODE (16u * 1024u * 1024u)
#define MAX_ITEMS 100000u
#define MAX_STRING (1024u * 1024u)
#define MAX_STACK 65536u
#define DEFAULT_MAX_STEPS 1000000u
#define FILE_LIMIT (MAX_BYTECODE + 70u)
#define MAX_INTEGER_BITS 13000u
#define MAX_INTEGER_DIGITS 4000u
#define MAX_BN_VALUES 100000u
#define MAX_BN_BYTES (64u * 1024u * 1024u)

typedef enum { V_NIL, V_BOOL, V_INT, V_STRING } ValueKind;
typedef struct {
    ValueKind kind;
    union {
        bool boolean;
        BIGNUM *integer;
        struct { char *data; size_t length; } string;
    } as;
} Value;
typedef enum {
    OP_CONST, OP_POP, OP_DUP, OP_LOAD_LOCAL, OP_STORE_LOCAL,
    OP_ADD, OP_SUB, OP_MUL, OP_MOD, OP_EQ, OP_NE, OP_LT, OP_LE,
    OP_GT, OP_GE, OP_NOT, OP_NEG, OP_JUMP, OP_JUMP_IF_FALSE, OP_HALT,
    OP_UNSUPPORTED
} Op;
typedef struct { Op op; int64_t operand; bool has_operand; } Instruction;
typedef struct { Value *constants; size_t constant_count; Instruction *code; size_t code_count; } Program;
typedef struct { BIGNUM **values; size_t count, capacity, bytes; } BNPool;

static void free_program(Program *program) {
    if (!program) return;
    if (program->constants) {
        for (size_t i = 0; i < program->constant_count; i++)
            if (program->constants[i].kind == V_STRING)
                free(program->constants[i].as.string.data);
    }
    free(program->constants);
    free(program->code);
    memset(program, 0, sizeof(*program));
}

static int fail(const char *message) {
    fprintf(stderr, "qvm1-seed: %s\n", message);
    return 1;
}


static void bn_pool_free(BNPool *pool) {
    if (!pool) return;
    for (size_t i = 0; i < pool->count; i++) BN_clear_free(pool->values[i]);
    free(pool->values);
    memset(pool, 0, sizeof(*pool));
}

static bool bn_pool_adopt(BNPool *pool, BIGNUM *value) {
    if (!pool || !value) { BN_clear_free(value); return false; }
    size_t bits = (size_t)BN_num_bits(value);
    size_t bytes = (bits + 7u) / 8u;
    if (pool->count >= MAX_BN_VALUES || bytes > MAX_BN_BYTES - pool->bytes) {
        BN_clear_free(value);
        return false;
    }
    if (pool->count == pool->capacity) {
        size_t next = pool->capacity ? pool->capacity * 2u : 32u;
        if (next > MAX_BN_VALUES) next = MAX_BN_VALUES;
        if (next <= pool->capacity || next > SIZE_MAX / sizeof(*pool->values)) {
            BN_clear_free(value);
            return false;
        }
        BIGNUM **grown = realloc(pool->values, next * sizeof(*pool->values));
        if (!grown) { BN_clear_free(value); return false; }
        pool->values = grown;
        pool->capacity = next;
    }
    pool->values[pool->count++] = value;
    pool->bytes += bytes;
    return true;
}

static BIGNUM *bn_from_decimal(BNPool *pool, const unsigned char *text, size_t length) {
    if (!text || !length || length > MAX_INTEGER_DIGITS || length > (size_t)INT_MAX)
        return NULL;
    char *decimal = malloc(length + 1u);
    if (!decimal) return NULL;
    memcpy(decimal, text, length);
    decimal[length] = '\0';
    BIGNUM *value = NULL;
    int consumed = BN_dec2bn(&value, decimal);
    free(decimal);
    if (!value || consumed != (int)length || (unsigned)BN_num_bits(value) > MAX_INTEGER_BITS) {
        BN_clear_free(value);
        return NULL;
    }
    if (!bn_pool_adopt(pool, value)) return NULL;
    return value;
}
static bool get_i64(struct json_object *value, int64_t *out) {
    if (!value || json_object_get_type(value) != json_type_int) return false;
    const char *text = json_object_to_json_string_ext(value, JSON_C_TO_STRING_PLAIN);
    if (!text) return false;
    errno = 0;
    char *end = NULL;
    long long parsed = strtoll(text, &end, 10);
    if (errno == ERANGE || end == text || *end != '\0') return false;
    *out = (int64_t)parsed;
    return true;
}

static bool get_value(struct json_object *item, Value *out, BIGNUM *integer) {
    if (!item || json_object_get_type(item) == json_type_null) {
        out->kind = V_NIL;
        return true;
    }
    enum json_type type = json_object_get_type(item);
    if (type == json_type_boolean) {
        out->kind = V_BOOL;
        out->as.boolean = json_object_get_boolean(item) != 0;
        return true;
    }
    if (type == json_type_int) {
        if (!integer) return false;
        out->kind = V_INT;
        out->as.integer = integer;
        return true;
    }
    if (type == json_type_string) {
        int length = json_object_get_string_len(item);
        const char *text = json_object_get_string(item);
        if (length < 0 || !text || (size_t)length > MAX_STRING) return false;
        char *copy = malloc((size_t)length + 1u);
        if (!copy) return false;
        memcpy(copy, text, (size_t)length);
        copy[(size_t)length] = '\0';
        out->kind = V_STRING;
        out->as.string.data = copy;
        out->as.string.length = (size_t)length;
        return true;
    }
    return false;
}

static int hex_digit(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static bool append_utf8(char *output, size_t capacity, size_t *used, uint32_t cp) {
    unsigned char bytes[4];
    size_t count;
    if (cp <= 0x7f) {
        bytes[0] = (unsigned char)cp;
        count = 1;
    } else if (cp <= 0x7ff) {
        bytes[0] = (unsigned char)(0xc0 | (cp >> 6));
        bytes[1] = (unsigned char)(0x80 | (cp & 0x3f));
        count = 2;
    } else if (cp <= 0xffff) {
        if (cp >= 0xd800 && cp <= 0xdfff) return false;
        bytes[0] = (unsigned char)(0xe0 | (cp >> 12));
        bytes[1] = (unsigned char)(0x80 | ((cp >> 6) & 0x3f));
        bytes[2] = (unsigned char)(0x80 | (cp & 0x3f));
        count = 3;
    } else if (cp <= 0x10ffff) {
        bytes[0] = (unsigned char)(0xf0 | (cp >> 18));
        bytes[1] = (unsigned char)(0x80 | ((cp >> 12) & 0x3f));
        bytes[2] = (unsigned char)(0x80 | ((cp >> 6) & 0x3f));
        bytes[3] = (unsigned char)(0x80 | (cp & 0x3f));
        count = 4;
    } else return false;
    if (*used > capacity || count > capacity - *used) return false;
    memcpy(output + *used, bytes, count);
    *used += count;
    return true;
}

/* json-c escapes non-ASCII while QVM1 canonical JSON stores valid UTF-8
   directly. Normalize serializer-produced Unicode escapes while preserving
   all other JSON escapes exactly, so literal text such as "\\u03bb" is not
   decoded a second time. */
static bool canonical_json_utf8(const char *input, char **output, size_t *output_length) {
    size_t length = strlen(input);
    char *normalized = malloc(length + 1);
    if (!normalized) return false;
    size_t i = 0, used = 0;
    while (i < length) {
        if (input[i] != '\\') {
            normalized[used++] = input[i++];
            continue;
        }
        if (i + 1 >= length) { free(normalized); return false; }
        if (input[i + 1] != 'u') {
            normalized[used++] = input[i++];
            normalized[used++] = input[i++];
            continue;
        }
        if (i + 5 >= length) { free(normalized); return false; }
        int h0 = hex_digit(input[i + 2]), h1 = hex_digit(input[i + 3]);
        int h2 = hex_digit(input[i + 4]), h3 = hex_digit(input[i + 5]);
        if (h0 < 0 || h1 < 0 || h2 < 0 || h3 < 0) { free(normalized); return false; }
        uint32_t cp = (uint32_t)((h0 << 12) | (h1 << 8) | (h2 << 4) | h3);
        size_t consumed = 6;
        if (cp >= 0xd800 && cp <= 0xdbff) {
            if (i + 11 >= length || input[i + 6] != '\\' || input[i + 7] != 'u') {
                free(normalized); return false;
            }
            int l0 = hex_digit(input[i + 8]), l1 = hex_digit(input[i + 9]);
            int l2 = hex_digit(input[i + 10]), l3 = hex_digit(input[i + 11]);
            if (l0 < 0 || l1 < 0 || l2 < 0 || l3 < 0) { free(normalized); return false; }
            uint32_t low = (uint32_t)((l0 << 12) | (l1 << 8) | (l2 << 4) | l3);
            if (low < 0xdc00 || low > 0xdfff) { free(normalized); return false; }
            cp = 0x10000u + ((cp - 0xd800u) << 10) + (low - 0xdc00u);
            consumed = 12;
        } else if (cp >= 0xdc00 && cp <= 0xdfff) {
            free(normalized); return false;
        }
        if (cp < 0x20) {
            memcpy(normalized + used, input + i, consumed);
            used += consumed;
        } else if (cp == '"') {
            normalized[used++] = '\\';
            normalized[used++] = '"';
        } else if (cp == '\\') {
            normalized[used++] = '\\';
            normalized[used++] = '\\';
        } else if (!append_utf8(normalized, length, &used, cp)) {
            free(normalized); return false;
        }
        i += consumed;
    }
    normalized[used] = '\0';
    *output = normalized;
    *output_length = used;
    return true;
}

static bool parse_opcode(const char *name, Op *out) {
#define OP(name_text, value) if (strcmp(name, name_text) == 0) { *out = value; return true; }
    OP("CONST", OP_CONST) OP("POP", OP_POP) OP("DUP", OP_DUP)
    OP("LOAD_LOCAL", OP_LOAD_LOCAL) OP("STORE_LOCAL", OP_STORE_LOCAL)
    OP("ADD", OP_ADD) OP("SUB", OP_SUB) OP("MUL", OP_MUL)
    OP("MOD", OP_MOD) OP("EQ", OP_EQ) OP("NE", OP_NE)
    OP("LT", OP_LT) OP("LE", OP_LE) OP("GT", OP_GT) OP("GE", OP_GE)
    OP("NOT", OP_NOT) OP("NEG", OP_NEG) OP("JUMP", OP_JUMP)
    OP("JUMP_IF_FALSE", OP_JUMP_IF_FALSE) OP("HALT", OP_HALT)
    OP("DIV", OP_UNSUPPORTED)
#undef OP
    return false;
}

static void append_unicode_escape(char *output, size_t *used, uint16_t cp) {
    static const char hex[] = "0123456789abcdef";
    output[(*used)++] = '\\';
    output[(*used)++] = 'u';
    output[(*used)++] = hex[(cp >> 12) & 15];
    output[(*used)++] = hex[(cp >> 8) & 15];
    output[(*used)++] = hex[(cp >> 4) & 15];
    output[(*used)++] = hex[cp & 15];
}

/* Validate UTF-8 and escape non-ASCII code points before handing JSON to
   json-c. The installed json-c parser rejects raw UTF-8 in strict mode, so
   parsing an ASCII-only escaped copy keeps the wire format unchanged. */
static bool json_escape_utf8(const unsigned char *data, size_t length,
                             char **output, size_t *output_length) {
    if (length > (SIZE_MAX - 1) / 3) return false;
    size_t capacity = length * 3 + 1;
    char *escaped = malloc(capacity);
    if (!escaped) return false;
    size_t i = 0, used = 0;
    while (i < length) {
        unsigned char c = data[i];
        if (c <= 0x7f) {
            escaped[used++] = (char)c;
            i++;
            continue;
        }
        uint32_t cp;
        size_t count;
        if (c >= 0xc2 && c <= 0xdf) {
            if (i + 1 >= length || (data[i + 1] & 0xc0) != 0x80) { free(escaped); return false; }
            cp = ((uint32_t)(c & 0x1f) << 6) | (uint32_t)(data[i + 1] & 0x3f);
            count = 2;
        } else if (c >= 0xe0 && c <= 0xef) {
            if (i + 2 >= length || (data[i + 1] & 0xc0) != 0x80 ||
                (data[i + 2] & 0xc0) != 0x80 ||
                (c == 0xe0 && data[i + 1] < 0xa0) ||
                (c == 0xed && data[i + 1] > 0x9f)) { free(escaped); return false; }
            cp = ((uint32_t)(c & 0x0f) << 12) |
                 ((uint32_t)(data[i + 1] & 0x3f) << 6) |
                 (uint32_t)(data[i + 2] & 0x3f);
            count = 3;
        } else if (c >= 0xf0 && c <= 0xf4) {
            if (i + 3 >= length || (data[i + 1] & 0xc0) != 0x80 ||
                (data[i + 2] & 0xc0) != 0x80 || (data[i + 3] & 0xc0) != 0x80 ||
                (c == 0xf0 && data[i + 1] < 0x90) ||
                (c == 0xf4 && data[i + 1] > 0x8f)) { free(escaped); return false; }
            cp = ((uint32_t)(c & 0x07) << 18) |
                 ((uint32_t)(data[i + 1] & 0x3f) << 12) |
                 ((uint32_t)(data[i + 2] & 0x3f) << 6) |
                 (uint32_t)(data[i + 3] & 0x3f);
            count = 4;
        } else {
            free(escaped);
            return false;
        }
        if (cp <= 0xffff) {
            append_unicode_escape(escaped, &used, (uint16_t)cp);
        } else {
            uint32_t value = cp - 0x10000u;
            uint16_t high = (uint16_t)(0xd800u + (value >> 10));
            uint16_t low = (uint16_t)(0xdc00u + (value & 0x3ffu));
            append_unicode_escape(escaped, &used, high);
            append_unicode_escape(escaped, &used, low);
        }
        i += count;
    }
    escaped[used] = '\0';
    *output = escaped;
    *output_length = used;
    return true;
}


static bool json_value_end(const unsigned char *data, size_t length,
                           size_t start, size_t *end) {
    if (start >= length) return false;
    if (data[start] == '"') {
        size_t i = start + 1u;
        while (i < length) {
            unsigned char c = data[i++];
            if (c == '\\') {
                if (i >= length) return false;
                i++;
            } else if (c == '"') {
                *end = i;
                return true;
            } else if (c < 0x20) {
                return false;
            }
        }
        return false;
    }
    if (data[start] == '[' || data[start] == '{') {
        size_t depth = 0;
        bool in_string = false, escaped = false;
        for (size_t i = start; i < length; i++) {
            unsigned char c = data[i];
            if (in_string) {
                if (escaped) escaped = false;
                else if (c == '\\') escaped = true;
                else if (c == '"') in_string = false;
                else if (c < 0x20) return false;
                continue;
            }
            if (c == '"') in_string = true;
            else if (c == '[' || c == '{') depth++;
            else if (c == ']' || c == '}') {
                if (!depth) return false;
                depth--;
                if (!depth) { *end = i + 1u; return true; }
            }
        }
        return false;
    }
    size_t i = start;
    while (i < length && data[i] != ',' && data[i] != ']' && data[i] != '}') i++;
    if (i == start) return false;
    *end = i;
    return true;
}

static bool canonical_integer_token(const unsigned char *text, size_t length) {
    if (!text || !length) return false;
    size_t i = 0;
    bool negative = false;
    if (text[i] == '-') { negative = true; i++; }
    if (i >= length) return false;
    if (text[i] == '0') return !negative && i + 1u == length;
    if (text[i] < '1' || text[i] > '9') return false;
    for (i++; i < length; i++)
        if (text[i] < '0' || text[i] > '9') return false;
    return true;
}

static size_t find_bytes(const unsigned char *data, size_t length,
                         const unsigned char *needle, size_t needle_length) {
    if (!needle_length || needle_length > length) return SIZE_MAX;
    for (size_t i = 0; i <= length - needle_length; i++)
        if (memcmp(data + i, needle, needle_length) == 0) return i;
    return SIZE_MAX;
}

/* json-c stores integers in a machine-sized type. Replace only top-level
   constant integer tokens with zero before parsing, retaining their exact
   decimal values as bounded OpenSSL BIGNUMs. The canonical JSON comparison
   then validates the rest of the document; integer lexical form is checked
   here before normalization. */
static bool normalize_integer_constants(const unsigned char *body, size_t length,
                                        BNPool *pool, char **normalized,
                                        size_t *normalized_length,
                                        BIGNUM ***integer_constants) {
    static const unsigned char marker[] = ",\"constants\":[";
    const size_t marker_length = sizeof(marker) - 1u;
    size_t marker_pos = find_bytes(body, length, marker, marker_length);
    if (marker_pos == SIZE_MAX) return false;

    char *copy = malloc(length + 1u);
    BIGNUM **integers = calloc(MAX_ITEMS, sizeof(*integers));
    if (!copy || !integers) { free(copy); free(integers); return false; }

    size_t used = marker_pos + marker_length;
    memcpy(copy, body, used);
    size_t pos = used, index = 0;
    bool first = true, closed = false;
    while (pos < length) {
        if (body[pos] == ']') {
            copy[used++] = ']';
            pos++;
            closed = true;
            break;
        }
        if (!first) {
            if (body[pos] != ',') goto invalid;
            copy[used++] = ',';
            pos++;
            if (pos >= length || body[pos] == ']') goto invalid;
        }
        size_t end = 0;
        if (!json_value_end(body, length, pos, &end) || end <= pos) goto invalid;
        size_t token_length = end - pos;
        if (canonical_integer_token(body + pos, token_length)) {
            if (index >= MAX_ITEMS) goto invalid;
            BIGNUM *value = bn_from_decimal(pool, body + pos, token_length);
            if (!value) goto invalid;
            integers[index] = value;
            copy[used++] = '0';
        } else {
            memcpy(copy + used, body + pos, token_length);
            used += token_length;
        }
        index++;
        pos = end;
        first = false;
        if (pos >= length || (body[pos] != ',' && body[pos] != ']')) goto invalid;
    }
    if (!closed) goto invalid;
    memcpy(copy + used, body + pos, length - pos);
    used += length - pos;
    copy[used] = '\0';
    *normalized = copy;
    *normalized_length = used;
    *integer_constants = integers;
    return true;

invalid:
    free(copy);
    free(integers);
    return false;
}

static bool parse_program(const unsigned char *body, size_t body_len,
                          Program *program, BNPool *pool) {
    char *normalized_body = NULL;
    size_t normalized_length = 0;
    BIGNUM **integer_constants = NULL;
    char *escaped_body = NULL;
    size_t escaped_length = 0;
    struct json_tokener *tok = NULL;
    struct json_object *root = NULL;
    bool ok = false;

    if (!normalize_integer_constants(body, body_len, pool, &normalized_body,
                                     &normalized_length, &integer_constants))
        goto done;
    if (!json_escape_utf8((const unsigned char *)normalized_body, normalized_length,
                          &escaped_body, &escaped_length))
        goto done;

    tok = json_tokener_new_ex(32);
    if (!tok) goto done;
    json_tokener_set_flags(tok, JSON_TOKENER_STRICT);
    root = json_tokener_parse_ex(tok, escaped_body, (int)escaped_length);
    bool parsed = root && json_tokener_get_error(tok) == json_tokener_success &&
                  json_tokener_get_parse_end(tok) == escaped_length;
    json_tokener_free(tok);
    tok = NULL;
    if (!parsed) goto done;

    const char *canonical = json_object_to_json_string_ext(root, JSON_C_TO_STRING_PLAIN);
    char *canonical_utf8 = NULL;
    size_t canonical_length = 0;
    bool normalized_ok = canonical &&
        canonical_json_utf8(canonical, &canonical_utf8, &canonical_length);
    bool canonical_match = normalized_ok &&
        canonical_length == normalized_length &&
        memcmp(canonical_utf8, normalized_body, normalized_length) == 0;
    free(canonical_utf8);
    if (!canonical_match || json_object_get_type(root) != json_type_object ||
        json_object_object_length(root) != 2)
        goto done;

    struct json_object *code = NULL, *constants = NULL;
    bool fields = json_object_object_get_ex(root, "code", &code) &&
                  json_object_object_get_ex(root, "constants", &constants) &&
                  code && constants && json_object_get_type(code) == json_type_array &&
                  json_object_get_type(constants) == json_type_array;
    if (!fields) goto done;
    size_t code_count = json_object_array_length(code);
    size_t constant_count = json_object_array_length(constants);
    if (code_count > MAX_ITEMS || constant_count > MAX_ITEMS) goto done;

    program->code = calloc(code_count ? code_count : 1u, sizeof(*program->code));
    program->constants = calloc(constant_count ? constant_count : 1u,
                                sizeof(*program->constants));
    program->code_count = code_count;
    program->constant_count = constant_count;
    if (!program->code || !program->constants) goto done;

    ok = true;
    for (size_t i = 0; i < constant_count && ok; i++)
        ok = get_value(json_object_array_get_idx(constants, i),
                       &program->constants[i], integer_constants[i]);
    for (size_t i = 0; i < code_count && ok; i++) {
        struct json_object *row = json_object_array_get_idx(code, i);
        if (!row || json_object_get_type(row) != json_type_array) { ok = false; break; }
        size_t n = json_object_array_length(row);
        if (n < 1 || n > 2) { ok = false; break; }
        struct json_object *name = json_object_array_get_idx(row, 0);
        if (!name || json_object_get_type(name) != json_type_string ||
            !parse_opcode(json_object_get_string(name), &program->code[i].op)) {
            ok = false;
            break;
        }
        program->code[i].has_operand = n == 2;
        if (n == 2 &&
            !get_i64(json_object_array_get_idx(row, 1), &program->code[i].operand)) {
            ok = false;
            break;
        }
    }

done:
    if (root) json_object_put(root);
    if (tok) json_tokener_free(tok);
    free(escaped_body);
    free(normalized_body);
    free(integer_constants);
    return ok;
}

static bool verify_stack(const Program *p) {
    size_t n = p->code_count;
    int32_t *heights = malloc((n + 1) * sizeof(*heights));
    size_t *queue = malloc((n + 1) * sizeof(*queue));
    if (!heights || !queue) { free(heights); free(queue); return false; }
    for (size_t i = 0; i <= n; i++) heights[i] = -1;
    size_t head = 0, tail = 0;
    heights[0] = 0; queue[tail++] = 0;
    bool ok = true;
    while (head < tail && ok) {
        size_t pc = queue[head++];
        if (pc == n) continue;
        Instruction ins = p->code[pc];
        int required = 0, delta = 0;
        switch (ins.op) {
            case OP_CONST: case OP_LOAD_LOCAL: delta = 1; break;
            case OP_POP: case OP_STORE_LOCAL: case OP_JUMP_IF_FALSE: required = 1; delta = -1; break;
            case OP_DUP: required = 1; delta = 1; break;
            case OP_ADD: case OP_SUB: case OP_MUL: case OP_MOD:
            case OP_EQ: case OP_NE: case OP_LT: case OP_LE: case OP_GT: case OP_GE:
                required = 2; delta = -1; break;
            case OP_NOT: case OP_NEG: required = 1; break;
            case OP_UNSUPPORTED: ok = false; continue;
            default: break;
        }
        int32_t next = heights[pc] + delta;
        if (heights[pc] < required || next < 0 || next > (int32_t)MAX_STACK) { ok = false; break; }
        size_t targets[2], count = 0;
        if (ins.op == OP_HALT) continue;
        if (ins.op == OP_JUMP) targets[count++] = (size_t)ins.operand;
        else if (ins.op == OP_JUMP_IF_FALSE) { targets[count++] = (size_t)ins.operand; targets[count++] = pc + 1; }
        else targets[count++] = pc + 1;
        for (size_t i = 0; i < count; i++) {
            size_t target = targets[i];
            if (target > n) { ok = false; break; }
            if (heights[target] == -1) { heights[target] = next; queue[tail++] = target; }
            else if (heights[target] != next) { ok = false; break; }
        }
    }
    free(heights); free(queue);
    return ok;
}

static bool validate(const Program *p) {
    for (size_t pc = 0; pc < p->code_count; pc++) {
        Instruction ins = p->code[pc];
        bool needs = ins.op == OP_CONST || ins.op == OP_LOAD_LOCAL || ins.op == OP_STORE_LOCAL ||
                     ins.op == OP_JUMP || ins.op == OP_JUMP_IF_FALSE;
        if (ins.has_operand != needs || ins.op == OP_UNSUPPORTED) return false;
        if (ins.op == OP_CONST && (ins.operand < 0 || (uint64_t)ins.operand >= p->constant_count)) return false;
        if ((ins.op == OP_LOAD_LOCAL || ins.op == OP_STORE_LOCAL) && (ins.operand < 0 || (uint64_t)ins.operand >= MAX_ITEMS)) return false;
        if ((ins.op == OP_JUMP || ins.op == OP_JUMP_IF_FALSE) && (ins.operand < 0 || (uint64_t)ins.operand > p->code_count)) return false;
    }
    return verify_stack(p);
}

static Value int_value(BIGNUM *n) {
    Value v = { .kind = V_INT, .as.integer = n };
    return v;
}
static Value bool_value(bool b) {
    Value v = { .kind = V_BOOL, .as.boolean = b };
    return v;
}
static bool pop(Value *stack, size_t *depth, Value *out) {
    if (!*depth) return false;
    *out = stack[--(*depth)];
    return true;
}
static bool push(Value *stack, size_t *depth, Value v) {
    if (*depth >= MAX_STACK) return false;
    stack[(*depth)++] = v;
    return true;
}

static bool integer_result(Op op, const BIGNUM *a, const BIGNUM *b,
                           BNPool *pool, BN_CTX *ctx, BIGNUM **out) {
    int bits_a = BN_num_bits(a), bits_b = BN_num_bits(b);
    if (op == OP_MUL && bits_a + bits_b > (int)MAX_INTEGER_BITS + 1) return false;
    if (op == OP_MOD && BN_is_zero(b)) return false;

    BIGNUM *value = BN_new();
    if (!value) return false;
    bool ok = false;
    if (op == OP_ADD) ok = BN_add(value, a, b) == 1;
    else if (op == OP_SUB) ok = BN_sub(value, a, b) == 1;
    else if (op == OP_MUL) ok = BN_mul(value, a, b, ctx) == 1;
    else if (op == OP_MOD) {
        BIGNUM *quotient = BN_new();
        if (quotient) {
            ok = BN_div(quotient, value, a, b, ctx) == 1;
            BN_free(quotient);
            if (ok && !BN_is_zero(value) &&
                BN_is_negative(value) != BN_is_negative(b))
                ok = BN_add(value, value, b) == 1;
        }
    }
    if (!ok || (unsigned)BN_num_bits(value) > MAX_INTEGER_BITS) {
        BN_clear_free(value);
        return false;
    }
    if (!bn_pool_adopt(pool, value)) return false;
    *out = value;
    return true;
}

static bool execute(const Program *p, BNPool *pool, Value *result) {
    Value *stack = calloc(MAX_STACK, sizeof(*stack));
    Value *locals = calloc(MAX_ITEMS, sizeof(*locals));
    bool *initialized = calloc(MAX_ITEMS, sizeof(*initialized));
    BN_CTX *ctx = BN_CTX_new();
    if (!stack || !locals || !initialized || !ctx) {
        free(stack);
        free(locals);
        free(initialized);
        BN_CTX_free(ctx);
        return false;
    }

    size_t depth = 0, pc = 0, steps = 0;
    bool ok = true;
    while (pc < p->code_count && ok) {
        if (++steps > DEFAULT_MAX_STEPS) { ok = false; break; }
        Instruction ins = p->code[pc++];
        Value a, b, v;
        switch (ins.op) {
            case OP_CONST:
                ok = push(stack, &depth, p->constants[(size_t)ins.operand]);
                break;
            case OP_POP:
                ok = pop(stack, &depth, &v);
                break;
            case OP_DUP:
                ok = pop(stack, &depth, &v) &&
                     push(stack, &depth, v) && push(stack, &depth, v);
                break;
            case OP_LOAD_LOCAL:
                if (!initialized[(size_t)ins.operand]) ok = false;
                else ok = push(stack, &depth, locals[(size_t)ins.operand]);
                break;
            case OP_STORE_LOCAL:
                ok = pop(stack, &depth, &v);
                if (ok) {
                    locals[(size_t)ins.operand] = v;
                    initialized[(size_t)ins.operand] = true;
                }
                break;
            case OP_NOT:
                ok = pop(stack, &depth, &v) && v.kind == V_BOOL;
                if (ok) ok = push(stack, &depth, bool_value(!v.as.boolean));
                break;
            case OP_NEG:
                ok = pop(stack, &depth, &v) && v.kind == V_INT;
                if (ok) {
                    BIGNUM *negative = BN_dup(v.as.integer);
                    if (!negative) ok = false;
                    else {
                        if (!BN_is_zero(negative))
                            BN_set_negative(negative, !BN_is_negative(negative));
                        if ((unsigned)BN_num_bits(negative) > MAX_INTEGER_BITS) {
                            BN_clear_free(negative);
                            ok = false;
                        } else if (!bn_pool_adopt(pool, negative)) {
                            ok = false;
                        } else {
                            ok = push(stack, &depth, int_value(negative));
                        }
                    }
                }
                break;
            case OP_JUMP:
                pc = (size_t)ins.operand;
                break;
            case OP_JUMP_IF_FALSE:
                ok = pop(stack, &depth, &v) && v.kind == V_BOOL;
                if (ok && !v.as.boolean) pc = (size_t)ins.operand;
                break;
            case OP_HALT:
                pc = p->code_count;
                break;
            default:
                ok = pop(stack, &depth, &b) && pop(stack, &depth, &a);
                if (!ok) break;
                if (ins.op == OP_EQ || ins.op == OP_NE) {
                    bool equal = a.kind == b.kind;
                    if (equal && a.kind == V_BOOL)
                        equal = a.as.boolean == b.as.boolean;
                    else if (equal && a.kind == V_INT)
                        equal = BN_cmp(a.as.integer, b.as.integer) == 0;
                    else if (equal && a.kind == V_STRING)
                        equal = a.as.string.length == b.as.string.length &&
                            memcmp(a.as.string.data, b.as.string.data,
                                   a.as.string.length) == 0;
                    ok = push(stack, &depth,
                              bool_value(ins.op == OP_EQ ? equal : !equal));
                } else if (a.kind == V_STRING && b.kind == V_STRING &&
                           (ins.op == OP_LT || ins.op == OP_LE ||
                            ins.op == OP_GT || ins.op == OP_GE)) {
                    size_t common = a.as.string.length < b.as.string.length
                        ? a.as.string.length : b.as.string.length;
                    int cmp = common
                        ? memcmp(a.as.string.data, b.as.string.data, common) : 0;
                    if (!cmp && a.as.string.length != b.as.string.length)
                        cmp = a.as.string.length < b.as.string.length ? -1 : 1;
                    bool comparison = ins.op == OP_LT ? cmp < 0 :
                                      ins.op == OP_LE ? cmp <= 0 :
                                      ins.op == OP_GT ? cmp > 0 : cmp >= 0;
                    ok = push(stack, &depth, bool_value(comparison));
                } else if (a.kind == V_INT && b.kind == V_INT) {
                    if (ins.op == OP_ADD || ins.op == OP_SUB ||
                        ins.op == OP_MUL || ins.op == OP_MOD) {
                        BIGNUM *computed = NULL;
                        ok = integer_result(ins.op, a.as.integer, b.as.integer,
                                            pool, ctx, &computed) &&
                             push(stack, &depth, int_value(computed));
                    } else if (ins.op == OP_LT || ins.op == OP_LE ||
                               ins.op == OP_GT || ins.op == OP_GE) {
                        int cmp = BN_cmp(a.as.integer, b.as.integer);
                        bool comparison = ins.op == OP_LT ? cmp < 0 :
                                          ins.op == OP_LE ? cmp <= 0 :
                                          ins.op == OP_GT ? cmp > 0 : cmp >= 0;
                        ok = push(stack, &depth, bool_value(comparison));
                    } else {
                        ok = false;
                    }
                } else {
                    ok = false;
                }
                break;
        }
    }

    if (ok) *result = depth ? stack[depth - 1u] : (Value){ .kind = V_NIL };
    free(stack);
    free(locals);
    free(initialized);
    BN_CTX_free(ctx);
    return ok;
}

static bool read_file(const char *path, unsigned char **out, size_t *length) {
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return false;
    struct stat before, after;
    if (fstat(fd, &before) != 0 || !S_ISREG(before.st_mode) || before.st_size < 70 ||
        (uint64_t)before.st_size > FILE_LIMIT) { close(fd); return false; }
    size_t capacity = (size_t)before.st_size;
    unsigned char *data = malloc(capacity + 1);
    if (!data) { close(fd); return false; }
    size_t used = 0;
    while (used < capacity) {
        ssize_t n = read(fd, data + used, capacity - used);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { free(data); close(fd); return false; }
        used += (size_t)n;
    }
    unsigned char extra;
    ssize_t more;
    do { more = read(fd, &extra, 1); } while (more < 0 && errno == EINTR);
    bool stable = fstat(fd, &after) == 0 && before.st_dev == after.st_dev &&
                  before.st_ino == after.st_ino && before.st_size == after.st_size && more == 0;
    close(fd);
    if (!stable) { free(data); return false; }
    *out = data; *length = used;
    return true;
}

static bool verify_envelope(const unsigned char *data, size_t length, const unsigned char **body, size_t *body_len) {
    if (length < 70 || memcmp(data, "QVM1\n", 5) || data[69] != '\n') return false;
    size_t n = length - 70;
    if (n > MAX_BYTECODE) return false;
    unsigned char digest[SHA256_DIGEST_LENGTH];
    SHA256(data + 70, n, digest);
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < 32; i++)
        if (data[5 + 2*i] != hex[digest[i] >> 4] || data[6 + 2*i] != hex[digest[i] & 15]) return false;
    *body = data + 70; *body_len = n;
    return true;
}

int main(int argc, char **argv) {
    if (argc != 2) return fail("usage: qvm1-seed <file.qvm>");
    unsigned char *data = NULL;
    size_t length = 0;
    if (!read_file(argv[1], &data, &length))
        return fail("file tidak valid, berubah, atau melebihi batas");

    const unsigned char *body = NULL;
    size_t body_len = 0;
    if (!verify_envelope(data, length, &body, &body_len)) {
        free(data);
        return fail("header atau checksum QVM1 tidak valid");
    }

    Program program = {0};
    BNPool pool = {0};
    bool parsed = parse_program(body, body_len, &program, &pool);
    free(data);
    if (!parsed) {
        free_program(&program);
        bn_pool_free(&pool);
        return fail("payload JSON tidak valid");
    }
    if (!validate(&program)) {
        free_program(&program);
        bn_pool_free(&pool);
        return fail("payload tidak valid atau di luar subset bootstrap seed");
    }

    Value result;
    bool ok = execute(&program, &pool, &result);
    if (!ok) {
        free_program(&program);
        bn_pool_free(&pool);
        return fail("eksekusi ditolak, gagal, atau melewati batas langkah/resource integer");
    }

    int output_status = 0;
    if (result.kind == V_NIL) puts("nil");
    else if (result.kind == V_BOOL) puts(result.as.boolean ? "true" : "false");
    else if (result.kind == V_STRING) {
        if (fwrite(result.as.string.data, 1, result.as.string.length, stdout) !=
                result.as.string.length || putchar('\n') == EOF)
            output_status = 1;
    } else {
        char *decimal = BN_bn2dec(result.as.integer);
        if (!decimal) output_status = 1;
        else {
            if (printf("%s\n", decimal) < 0) output_status = 1;
            OPENSSL_free(decimal);
        }
    }

    free_program(&program);
    bn_pool_free(&pool);
    if (output_status) return fail("gagal menulis hasil QVM");
    return 0;
}
