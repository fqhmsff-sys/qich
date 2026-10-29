"""Compile a deliberately small, semantics-locked Qich AST subset to QVM1.

This is the first compiler slice for self-hosting. Unsupported syntax fails closed
instead of silently changing Qich semantics.
"""
from qich.compiler import ast as A
from .bytecode import _validate


class CompileError(ValueError):
    pass


_BIN = {
    "+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD",
    "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE",
}
_UNARY = {"-": "NEG", "!": "NOT", "not": "NOT"}


class _Compiler:
    def __init__(self):
        self.constants = []
        self.code = []
        self.locals = {}

    def const(self, value):
        # Reuse constants where equality and type agree. bool must not alias int.
        for i, old in enumerate(self.constants):
            if type(old) is type(value) and old == value:
                return i
        self.constants.append(value)
        return len(self.constants) - 1

    def emit(self, op, arg=None):
        self.code.append([op] if arg is None else [op, arg])
        return len(self.code) - 1

    def local(self, name, create=False):
        if name not in self.locals:
            if not create:
                raise CompileError("variabel belum dideklarasi: %s" % name)
            self.locals[name] = len(self.locals)
        return self.locals[name]

    def expr(self, node):
        if isinstance(node, A.Num):
            self.emit("CONST", self.const(node.value))
        elif isinstance(node, A.Str):
            self.emit("CONST", self.const(node.value))
        elif isinstance(node, A.Bool):
            self.emit("CONST", self.const(node.value))
        elif isinstance(node, A.Nil):
            self.emit("CONST", self.const(None))
        elif isinstance(node, A.Ident):
            self.emit("LOAD_LOCAL", self.local(node.name))
        elif isinstance(node, A.Unary) and node.op in _UNARY:
            self.expr(node.operand)
            self.emit(_UNARY[node.op])
        elif isinstance(node, A.Binary) and node.op in _BIN:
            self.expr(node.left)
            self.expr(node.right)
            self.emit(_BIN[node.op])
        elif isinstance(node, A.Ternary):
            self.expr(node.cond)
            jf = self.emit("JUMP_IF_FALSE", 0)
            self.expr(node.a)
            end = self.emit("JUMP", 0)
            self.code[jf][1] = len(self.code)
            self.expr(node.b)
            self.code[end][1] = len(self.code)
        else:
            raise CompileError("AST belum didukung QVM1: %s" % type(node).__name__)

    def program(self, program):
        if not isinstance(program, A.Program):
            raise CompileError("compiler QVM membutuhkan Program Qich")
        if not program.body:
            self.emit("CONST", self.const(None))
        for i, stmt in enumerate(program.body):
            produces = False
            if isinstance(stmt, A.ExprStmt):
                self.expr(stmt.expr)
                produces = True
            elif isinstance(stmt, A.Let):
                self.expr(stmt.value if stmt.value is not None else A.Nil())
                self.emit("STORE_LOCAL", self.local(stmt.name, create=True))
            elif isinstance(stmt, A.Assign) and isinstance(stmt.target, A.Ident) and stmt.op == "=":
                self.expr(stmt.value)
                self.emit("STORE_LOCAL", self.local(stmt.target.name))
            else:
                raise CompileError("statement belum didukung QVM1: %s" % type(stmt).__name__)
            if produces and i + 1 < len(program.body):
                self.emit("POP")
        if program.body and not isinstance(program.body[-1], A.ExprStmt):
            self.emit("CONST", self.const(None))
        self.emit("HALT")
        result = {"constants": self.constants, "code": self.code}
        return _validate(result)


def compile_program(program):
    """Compile the supported Qich AST subset into a validated QVM1 program."""
    return _Compiler().program(program)
