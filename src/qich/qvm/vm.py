"""Small reference executor for the QVM v1 instruction set.

This executor is intentionally capability-free and bounded.  It is the semantic
oracle for a future bootstrap VM implemented outside the Python reference
runtime; it does not make Qich self-hosted by itself.
"""
from .bytecode import BytecodeError, _validate

DEFAULT_MAX_STEPS = 1_000_000
DEFAULT_MAX_STACK = 65_536


class VMError(RuntimeError):
    pass


def execute(program, *, max_steps=DEFAULT_MAX_STEPS, max_stack=DEFAULT_MAX_STACK):
    """Execute a validated QVM program and return the top stack value.

    JUMP targets may point one instruction past the code to terminate cleanly.
    Resource budgets are mandatory positive integers to keep malformed programs
    from consuming unbounded CPU or stack memory.
    """
    _validate(program)
    if type(max_steps) is not int or isinstance(max_steps, bool) or max_steps <= 0:
        raise VMError("max_steps QVM harus integer positif")
    if type(max_stack) is not int or isinstance(max_stack, bool) or max_stack <= 0:
        raise VMError("max_stack QVM harus integer positif")

    constants = program["constants"]
    code = program["code"]
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
        stack.append(value)

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
        elif op in ("ADD", "SUB", "MUL", "DIV", "MOD", "EQ", "NE", "LT", "LE", "GT", "GE"):
            right = pop()
            left = pop()
            try:
                if op == "ADD":
                    value = left + right
                elif op == "SUB":
                    value = left - right
                elif op == "MUL":
                    value = left * right
                elif op == "DIV":
                    value = left / right
                elif op == "MOD":
                    value = left % right
                elif op == "EQ":
                    value = left == right
                elif op == "NE":
                    value = left != right
                elif op == "LT":
                    value = left < right
                elif op == "LE":
                    value = left <= right
                elif op == "GT":
                    value = left > right
                else:
                    value = left >= right
            except (ArithmeticError, TypeError, ValueError) as exc:
                raise VMError("operasi QVM gagal: %s" % op) from exc
            push(value)
        elif op == "NOT":
            push(not pop())
        elif op == "NEG":
            value = pop()
            try:
                push(-value)
            except TypeError as exc:
                raise VMError("operasi QVM gagal: NEG") from exc
        elif op == "JUMP":
            pc = ins[1]
        elif op == "JUMP_IF_FALSE":
            condition = pop()
            if not condition:
                pc = ins[1]
        elif op == "HALT":
            break
        else:  # _validate should make this unreachable.
            raise BytecodeError("opcode QVM tidak dikenal: %s" % op)

    return stack[-1] if stack else None
