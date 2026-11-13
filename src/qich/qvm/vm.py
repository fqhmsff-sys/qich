"""Bounded, capability-free reference executor for QVM v1."""
from dataclasses import dataclass
import math

from .bytecode import (
    BytecodeError, MAX_INTEGER_BITS, MAX_STACK, MAX_STRING, _validate,
)
from ..runtime.values import q_eq

DEFAULT_MAX_STEPS = 1_000_000
DEFAULT_MAX_STACK = MAX_STACK


class VMError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _PreparedProgram:
    """Immutable, validated snapshot for repeated execution."""

    constants: tuple
    code: tuple


def prepare(program):
    """Copy, validate, and freeze a QVM program for repeated execution.

    Validation is performed against the copied snapshot. Later mutations to
    caller-owned dictionaries/lists therefore cannot alter prepared code.
    """
    if type(program) is not dict or set(program) != {"constants", "code"}:
        raise VMError("bytecode QVM tidak valid")
    constants = program["constants"]
    code = program["code"]
    if type(constants) is not list or type(code) is not list:
        raise VMError("bytecode QVM tidak valid")
    snapshot = {
        "constants": list(constants),
        "code": [list(ins) if type(ins) is list else ins for ins in code],
    }
    try:
        _validate(snapshot)
    except BytecodeError as exc:
        raise VMError("bytecode QVM tidak valid") from exc
    return _PreparedProgram(
        tuple(snapshot["constants"]),
        tuple(tuple(ins) for ins in snapshot["code"]),
    )


def _number(value):
    return type(value) in (int, float)


def _checked(value):
    if type(value) is int and value.bit_length() > MAX_INTEGER_BITS:
        raise VMError("batas ukuran integer QVM terlampaui")
    if type(value) is float and not math.isfinite(value):
        raise VMError("hasil float QVM tidak finite")
    if type(value) is str:
        if len(value) > MAX_STRING or len(value.encode("utf-8")) > MAX_STRING:
            raise VMError("batas ukuran string QVM terlampaui")
    return value


def _binary(op, left, right):
    numeric = _number(left) and _number(right)
    if op == "EQ":
        return q_eq(left, right)
    if op == "NE":
        return not q_eq(left, right)
    if op in ("LT", "LE", "GT", "GE"):
        compatible = numeric or (type(left) is str and type(right) is str)
        if not compatible:
            raise VMError("operand perbandingan QVM tidak kompatibel")
        if op == "LT":
            return left < right
        if op == "LE":
            return left <= right
        if op == "GT":
            return left > right
        return left >= right
    if op == "ADD":
        if numeric or (type(left) is str and type(right) is str):
            return left + right
        raise VMError("ADD QVM membutuhkan dua angka atau dua string")
    if op == "SUB":
        if numeric:
            return left - right
        raise VMError("SUB QVM membutuhkan dua angka")
    if op == "MUL":
        if numeric:
            return left * right
        if type(left) is str and type(right) is int:
            if len(left) * max(right, 0) > MAX_STRING:
                raise VMError("hasil string QVM terlalu besar")
            return left * right
        if type(right) is str and type(left) is int:
            if len(right) * max(left, 0) > MAX_STRING:
                raise VMError("hasil string QVM terlalu besar")
            return right * left
        raise VMError("MUL QVM membutuhkan angka atau string dikali int")
    if op == "DIV":
        if not numeric:
            raise VMError("DIV QVM membutuhkan dua angka")
        if right == 0:
            raise VMError("pembagian QVM dengan nol")
        return left / right
    if op == "MOD":
        if not numeric:
            raise VMError("MOD QVM membutuhkan dua angka")
        if right == 0:
            raise VMError("modulo QVM dengan nol")
        return left % right
    raise BytecodeError("opcode binary QVM tidak dikenal: %s" % op)


def execute(program, *, max_steps=DEFAULT_MAX_STEPS, max_stack=DEFAULT_MAX_STACK):
    """Execute validated QVM and return the top stack value.

    A jump may target one instruction past the end to terminate cleanly.
    Positive step and stack budgets are mandatory.
    """
    if type(program) is _PreparedProgram:
        constants = program.constants
        code = program.code
    else:
        # Snapshot before validation so caller mutation cannot change the
        # bytecode state that is executed after verification.
        prepared = prepare(program)
        constants = prepared.constants
        code = prepared.code
    if type(max_steps) is not int or isinstance(max_steps, bool) or max_steps <= 0:
        raise VMError("max_steps QVM harus integer positif")
    if type(max_stack) is not int or isinstance(max_stack, bool) or max_stack <= 0:
        raise VMError("max_stack QVM harus integer positif")

    stack = []
    locals_ = {}
    pc = 0
    steps = 0

    def pop():
        if not stack:
            raise VMError("stack QVM kosong")
        return stack.pop()

    def push(value):
        if len(stack) >= max_stack:
            raise VMError("batas stack QVM terlampaui")
        stack.append(_checked(value))

    while pc < len(code):
        steps += 1
        if steps > max_steps:
            raise VMError("batas langkah QVM terlampaui")

        ins = code[pc]
        op = ins[0]
        pc += 1

        if op == "CONST":
            push(constants[ins[1]])
        elif op == "POP":
            pop()
        elif op == "LOAD_LOCAL":
            if ins[1] not in locals_:
                raise VMError("local QVM belum diinisialisasi")
            push(locals_[ins[1]])
        elif op == "STORE_LOCAL":
            locals_[ins[1]] = pop()
        elif op == "DUP":
            value = pop()
            push(value)
            push(value)
        elif op in ("ADD", "SUB", "MUL", "DIV", "MOD",
                    "EQ", "NE", "LT", "LE", "GT", "GE"):
            right = pop()
            left = pop()
            try:
                push(_binary(op, left, right))
            except (ArithmeticError, TypeError, ValueError) as exc:
                raise VMError("operasi QVM gagal: %s" % op) from exc
        elif op == "NOT":
            value = pop()
            if type(value) is not bool:
                raise VMError("NOT QVM membutuhkan bool")
            push(not value)
        elif op == "NEG":
            value = pop()
            if not _number(value):
                raise VMError("NEG QVM membutuhkan angka")
            push(-value)
        elif op == "JUMP":
            pc = ins[1]
        elif op == "JUMP_IF_FALSE":
            condition = pop()
            if type(condition) is not bool:
                raise VMError("kondisi QVM harus bool")
            if not condition:
                pc = ins[1]
        elif op == "HALT":
            break
        else:  # _validate makes this unreachable for well-formed programs.
            raise BytecodeError("opcode QVM tidak dikenal: %s" % op)

    return stack[-1] if stack else None
