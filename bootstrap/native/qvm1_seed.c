#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <json-c/json.h>
#include <limits.h>
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
#define MAX_STACK 65536u
#define DEFAULT_MAX_STEPS 1000000u
#define FILE_LIMIT (MAX_BYTECODE + 70u)

typedef enum { V_NIL, V_BOOL, V_INT } ValueKind;
typedef struct { ValueKind kind; union { bool boolean; int64_t integer; } as; } Value;
typedef enum {
    OP_CONST, OP_POP, OP_DUP, OP_LOAD_LOCAL, OP_STORE_LOCAL,
    OP_ADD, OP_SUB, OP_MUL, OP_MOD, OP_EQ, OP_NE, OP_LT, OP_LE,
    OP_GT, OP_GE, OP_NOT, OP_NEG, OP_JUMP, OP_JUMP_IF_FALSE, OP_HALT,
    OP_UNSUPPORTED
} Op;
typedef struct { Op op; int64_t operand; bool has_operand; } Instruction;
typedef struct { Value *constants; size_t constant_count; Instruction *code; size_t code_count; } Program;

static int fail(const char *message) {
    fprintf(stderr, "qvm1-seed: %s\n", message);
    return 1;
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

static bool get_value(struct json_object *item, Value *out) {
    if (!item || json_object_get_type(item) == json_type_null) { out->kind = V_NIL; return true; }
    enum json_type type = json_object_get_type(item);
    if (type == json_type_boolean) { out->kind = V_BOOL; out->as.boolean = json_object_get_boolean(item) != 0; return true; }
    if (type == json_type_int) { out->kind = V_INT; return get_i64(item, &out->as.integer); }
    return false;
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

static bool parse_program(const unsigned char *body, size_t body_len, Program *program) {
    struct json_tokener *tok = json_tokener_new_ex(32);
    if (!tok) return false;
    json_tokener_set_flags(tok, JSON_TOKENER_STRICT | JSON_TOKENER_VALIDATE_UTF8);
    struct json_object *root = json_tokener_parse_ex(tok, (const char *)body, (int)body_len);
    bool parsed = root && json_tokener_get_error(tok) == json_tokener_success &&
                  json_tokener_get_parse_end(tok) == body_len;
    json_tokener_free(tok);
    if (!parsed) { if (root) json_object_put(root); return false; }

    /* Canonical form also rejects duplicate keys and alternate encodings. */
    const char *canonical = json_object_to_json_string_ext(root, JSON_C_TO_STRING_PLAIN);
    bool canonical_match = canonical && strlen(canonical) == body_len && memcmp(canonical, body, body_len) == 0;
    if (!canonical_match || json_object_get_type(root) != json_type_object || json_object_object_length(root) != 2) {
        json_object_put(root); return false;
    }
    struct json_object *code = NULL, *constants = NULL;
    bool fields = json_object_object_get_ex(root, "code", &code) &&
                  json_object_object_get_ex(root, "constants", &constants) &&
                  code && constants && json_object_get_type(code) == json_type_array &&
                  json_object_get_type(constants) == json_type_array;
    if (!fields) { json_object_put(root); return false; }
    size_t code_count = json_object_array_length(code);
    size_t constant_count = json_object_array_length(constants);
    if (code_count > MAX_ITEMS || constant_count > MAX_ITEMS) { json_object_put(root); return false; }

    program->code = calloc(code_count ? code_count : 1, sizeof(*program->code));
    program->constants = calloc(constant_count ? constant_count : 1, sizeof(*program->constants));
    if (!program->code || !program->constants) { json_object_put(root); return false; }
    program->code_count = code_count;
    program->constant_count = constant_count;

    bool ok = true;
    for (size_t i = 0; i < constant_count && ok; i++)
        ok = get_value(json_object_array_get_idx(constants, i), &program->constants[i]);
    for (size_t i = 0; i < code_count && ok; i++) {
        struct json_object *row = json_object_array_get_idx(code, i);
        if (!row || json_object_get_type(row) != json_type_array) { ok = false; break; }
        size_t n = json_object_array_length(row);
        if (n < 1 || n > 2) { ok = false; break; }
        struct json_object *name = json_object_array_get_idx(row, 0);
        if (!name || json_object_get_type(name) != json_type_string ||
            !parse_opcode(json_object_get_string(name), &program->code[i].op)) { ok = false; break; }
        program->code[i].has_operand = n == 2;
        if (n == 2 && !get_i64(json_object_array_get_idx(row, 1), &program->code[i].operand)) { ok = false; break; }
    }
    json_object_put(root);
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

static bool add_i64(int64_t a, int64_t b, int64_t *out) {
    if ((b > 0 && a > INT64_MAX - b) || (b < 0 && a < INT64_MIN - b)) return false;
    *out = a + b; return true;
}
static bool sub_i64(int64_t a, int64_t b, int64_t *out) {
    if ((b < 0 && a > INT64_MAX + b) || (b > 0 && a < INT64_MIN + b)) return false;
    *out = a - b; return true;
}
static bool mul_i64(int64_t a, int64_t b, int64_t *out) {
    if (a == 0 || b == 0) { *out = 0; return true; }
    if ((a == -1 && b == INT64_MIN) || (b == -1 && a == INT64_MIN)) return false;
    if (a > 0) {
        if ((b > 0 && a > INT64_MAX / b) || (b < 0 && b < INT64_MIN / a)) return false;
    } else if ((b > 0 && a < INT64_MIN / b) || (b < 0 && a < INT64_MAX / b)) return false;
    *out = a * b; return true;
}
static Value int_value(int64_t n) { Value v = { .kind = V_INT, .as.integer = n }; return v; }
static Value bool_value(bool b) { Value v = { .kind = V_BOOL, .as.boolean = b }; return v; }
static bool pop(Value *stack, size_t *depth, Value *out) { if (!*depth) return false; *out = stack[--*depth]; return true; }
static bool push(Value *stack, size_t *depth, Value v) { if (*depth >= MAX_STACK) return false; stack[(*depth)++] = v; return true; }

static bool execute(const Program *p, Value *result) {
    Value *stack = calloc(MAX_STACK, sizeof(*stack));
    Value *locals = calloc(MAX_ITEMS, sizeof(*locals));
    bool *initialized = calloc(MAX_ITEMS, sizeof(*initialized));
    if (!stack || !locals || !initialized) { free(stack); free(locals); free(initialized); return false; }
    size_t depth = 0, pc = 0, steps = 0;
    bool ok = true;
    while (pc < p->code_count && ok) {
        if (++steps > DEFAULT_MAX_STEPS) { ok = false; break; }
        Instruction ins = p->code[pc++];
        Value a, b, v;
        int64_t n;
        switch (ins.op) {
            case OP_CONST: ok = push(stack, &depth, p->constants[(size_t)ins.operand]); break;
            case OP_POP: ok = pop(stack, &depth, &v); break;
            case OP_DUP: ok = pop(stack, &depth, &v) && push(stack, &depth, v) && push(stack, &depth, v); break;
            case OP_LOAD_LOCAL:
                if (!initialized[(size_t)ins.operand]) ok = false;
                else ok = push(stack, &depth, locals[(size_t)ins.operand]);
                break;
            case OP_STORE_LOCAL:
                ok = pop(stack, &depth, &v);
                if (ok) { locals[(size_t)ins.operand] = v; initialized[(size_t)ins.operand] = true; }
                break;
            case OP_NOT:
                ok = pop(stack, &depth, &v) && v.kind == V_BOOL;
                if (ok) ok = push(stack, &depth, bool_value(!v.as.boolean));
                break;
            case OP_NEG:
                ok = pop(stack, &depth, &v) && v.kind == V_INT && v.as.integer != INT64_MIN;
                if (ok) ok = push(stack, &depth, int_value(-v.as.integer));
                break;
            case OP_JUMP: pc = (size_t)ins.operand; break;
            case OP_JUMP_IF_FALSE:
                ok = pop(stack, &depth, &v) && v.kind == V_BOOL;
                if (ok && !v.as.boolean) pc = (size_t)ins.operand;
                break;
            case OP_HALT: pc = p->code_count; break;
            default:
                ok = pop(stack, &depth, &b) && pop(stack, &depth, &a);
                if (!ok) break;
                if (ins.op == OP_EQ || ins.op == OP_NE) {
                    bool equal = a.kind == b.kind;
                    if (equal && a.kind == V_BOOL) equal = a.as.boolean == b.as.boolean;
                    else if (equal && a.kind == V_INT) equal = a.as.integer == b.as.integer;
                    ok = push(stack, &depth, bool_value(ins.op == OP_EQ ? equal : !equal));
                } else if (a.kind != V_INT || b.kind != V_INT) ok = false;
                else if (ins.op == OP_ADD) ok = add_i64(a.as.integer, b.as.integer, &n) && push(stack, &depth, int_value(n));
                else if (ins.op == OP_SUB) ok = sub_i64(a.as.integer, b.as.integer, &n) && push(stack, &depth, int_value(n));
                else if (ins.op == OP_MUL) ok = mul_i64(a.as.integer, b.as.integer, &n) && push(stack, &depth, int_value(n));
                else if (ins.op == OP_MOD) {
                    if (!b.as.integer) ok = false;
                    else if (a.as.integer == INT64_MIN && b.as.integer == -1) ok = push(stack, &depth, int_value(0));
                    else { n = a.as.integer % b.as.integer; if (n && ((n < 0) != (b.as.integer < 0))) n += b.as.integer; ok = push(stack, &depth, int_value(n)); }
                } else if (ins.op == OP_LT) ok = push(stack, &depth, bool_value(a.as.integer < b.as.integer));
                else if (ins.op == OP_LE) ok = push(stack, &depth, bool_value(a.as.integer <= b.as.integer));
                else if (ins.op == OP_GT) ok = push(stack, &depth, bool_value(a.as.integer > b.as.integer));
                else if (ins.op == OP_GE) ok = push(stack, &depth, bool_value(a.as.integer >= b.as.integer));
                else ok = false;
                break;
        }
    }
    if (ok) *result = depth ? stack[depth - 1] : (Value){ .kind = V_NIL };
    free(stack); free(locals); free(initialized);
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
    unsigned char *data = NULL; size_t length = 0;
    if (!read_file(argv[1], &data, &length)) return fail("file tidak valid, berubah, atau melebihi batas");
    const unsigned char *body = NULL; size_t body_len = 0;
    if (!verify_envelope(data, length, &body, &body_len)) { free(data); return fail("header atau checksum QVM1 tidak valid"); }
    Program program = {0};
    bool parsed = parse_program(body, body_len, &program);
    free(data);
    if (!parsed || !validate(&program)) {
        free(program.constants); free(program.code);
        return fail("payload tidak valid atau di luar subset bootstrap seed");
    }
    Value result; bool ok = execute(&program, &result);
    free(program.constants); free(program.code);
    if (!ok) return fail("eksekusi ditolak, gagal, atau melewati batas langkah");
    if (result.kind == V_NIL) puts("nil");
    else if (result.kind == V_BOOL) puts(result.as.boolean ? "true" : "false");
    else printf("%" PRId64 "\n", result.as.integer);
    return 0;
}
