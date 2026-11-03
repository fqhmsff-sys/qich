"""QVM v1 bytecode envelope.

The format is deterministic, versioned and bounded so a future native bootstrap
VM can implement it without inheriting Python object semantics.
"""
import hashlib
import hmac
import json
import math

MAGIC = b"QVM1\n"
MAX_BYTECODE = 16 * 1024 * 1024
MAX_CONSTANTS = 100_000
MAX_INSTRUCTIONS = 100_000
MAX_STRING = 1024 * 1024
MAX_INTEGER_BITS = 13_000
MAX_STACK = 65_536

# Capability-free instruction set. New operations require conformance tests.
OPCODES = frozenset({
    "CONST", "POP", "DUP", "LOAD_LOCAL", "STORE_LOCAL",
    "ADD", "SUB", "MUL", "DIV", "MOD",
    "EQ", "NE", "LT", "LE", "GT", "GE",
    "NOT", "NEG", "JUMP", "JUMP_IF_FALSE", "HALT",
})


class BytecodeError(ValueError):
    pass


def _constant(value):
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        if value.bit_length() > MAX_INTEGER_BITS:
            raise BytecodeError("integer constant QVM terlalu besar")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise BytecodeError("float constant QVM harus finite")
        return value
    if type(value) is str:
        try:
            size = len(value.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise BytecodeError("string constant bukan UTF-8 valid") from exc
        if size > MAX_STRING:
            raise BytecodeError("string constant terlalu besar")
        return value
    raise BytecodeError("tipe constant QVM tidak didukung")



def _verify_stack(code):
    """Verify stack depth on every reachable control-flow path."""
    if not code:
        return

    heights = {0: 0}
    pending = [0]
    binary = {
        "ADD", "SUB", "MUL", "DIV", "MOD",
        "EQ", "NE", "LT", "LE", "GT", "GE",
    }

    def enqueue(target, height):
        previous = heights.get(target)
        if previous is None:
            heights[target] = height
            pending.append(target)
        elif previous != height:
            raise BytecodeError(
                "tinggi stack QVM tidak konsisten pada pc %d" % target
            )

    while pending:
        pc = pending.pop()
        if pc == len(code):
            continue

        height = heights[pc]
        op = code[pc][0]
        if op in ("CONST", "LOAD_LOCAL"):
            required, delta = 0, 1
        elif op in ("POP", "STORE_LOCAL", "JUMP_IF_FALSE"):
            required, delta = 1, -1
        elif op == "DUP":
            required, delta = 1, 1
        elif op in binary:
            required, delta = 2, -1
        elif op in ("NOT", "NEG"):
            required, delta = 1, 0
        else:
            required, delta = 0, 0

        if height < required:
            raise BytecodeError(
                "stack underflow QVM pada pc %d (%s)" % (pc, op)
            )
        next_height = height + delta
        if next_height > MAX_STACK:
            raise BytecodeError(
                "batas stack statis QVM terlampaui pada pc %d" % pc
            )

        if op == "HALT":
            continue
        if op == "JUMP":
            enqueue(code[pc][1], next_height)
        elif op == "JUMP_IF_FALSE":
            enqueue(code[pc][1], next_height)
            enqueue(pc + 1, next_height)
        else:
            enqueue(pc + 1, next_height)


def _validate(program):
    if type(program) is not dict or set(program) != {"constants", "code"}:
        raise BytecodeError("struktur program QVM tidak valid")
    constants = program["constants"]
    code = program["code"]
    if type(constants) is not list or len(constants) > MAX_CONSTANTS:
        raise BytecodeError("constant pool QVM tidak valid atau terlalu besar")
    if type(code) is not list or len(code) > MAX_INSTRUCTIONS:
        raise BytecodeError("instruction stream QVM tidak valid atau terlalu besar")
    for value in constants:
        _constant(value)
    for pc, ins in enumerate(code):
        if type(ins) is not list or not 1 <= len(ins) <= 2 or type(ins[0]) is not str:
            raise BytecodeError("instruksi QVM tidak valid pada pc %d" % pc)
        op = ins[0]
        if op not in OPCODES:
            raise BytecodeError("opcode QVM tidak dikenal: %s" % op)
        if len(ins) == 2 and (type(ins[1]) is not int or isinstance(ins[1], bool)):
            raise BytecodeError("operand QVM harus integer")
        needs_operand = op in ("CONST", "LOAD_LOCAL", "STORE_LOCAL", "JUMP", "JUMP_IF_FALSE")
        if needs_operand and len(ins) != 2:
            raise BytecodeError("opcode %s membutuhkan operand" % op)
        if not needs_operand and len(ins) != 1:
            raise BytecodeError("opcode %s tidak menerima operand" % op)
        if op in ("LOAD_LOCAL", "STORE_LOCAL") and not 0 <= ins[1] < MAX_CONSTANTS:
            raise BytecodeError("slot local QVM di luar batas")
        if op == "CONST" and not 0 <= ins[1] < len(constants):
            raise BytecodeError("indeks constant QVM di luar batas")
        if op in ("JUMP", "JUMP_IF_FALSE") and not 0 <= ins[1] <= len(code):
            raise BytecodeError("target jump QVM di luar batas")
    _verify_stack(code)
    return program


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BytecodeError("kunci JSON QVM duplikat")
        result[key] = value
    return result


def encode(program):
    _validate(program)
    try:
        body = json.dumps(
            program, ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeError) as exc:
        raise BytecodeError("program QVM tidak dapat diserialisasi") from exc
    if len(body) > MAX_BYTECODE:
        raise BytecodeError("bytecode QVM terlalu besar")
    digest = hashlib.sha256(body).hexdigest().encode("ascii")
    return MAGIC + digest + b"\n" + body


def decode(data):
    if type(data) is not bytes or len(data) > MAX_BYTECODE + 70:
        raise BytecodeError("bytecode QVM tidak valid atau terlalu besar")
    if not data.startswith(MAGIC):
        raise BytecodeError("magic/versi QVM tidak didukung")
    rest = data[len(MAGIC):]
    nl = rest.find(b"\n")
    if nl != 64:
        raise BytecodeError("header QVM rusak")
    digest, body = rest[:64], rest[65:]
    actual = hashlib.sha256(body).hexdigest().encode("ascii")
    if not hmac.compare_digest(actual, digest):
        raise BytecodeError("checksum QVM tidak cocok")
    try:
        program = json.loads(body, object_pairs_hook=_unique_object)
    except BytecodeError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise BytecodeError("payload QVM tidak valid") from exc
    return _validate(program)
