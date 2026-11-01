"""Differential checks between Qich reference semantics and the QVM subset."""
import unittest

from qich.compiler import parse, ast as A
from qich.qvm.compiler import compile_program
from qich.qvm.vm import execute
from qich.runtime.interp import arith, compare
from qich.runtime.values import q_eq


def reference_expr(node, env):
    if isinstance(node, A.Num):
        return node.value
    if isinstance(node, A.Str):
        return node.value
    if isinstance(node, A.Bool):
        return node.value
    if isinstance(node, A.Nil):
        return None
    if isinstance(node, A.Ident):
        return env[node.name]
    if isinstance(node, A.Unary):
        value = reference_expr(node.operand, env)
        if node.op in ("!", "not"):
            if type(value) is not bool:
                raise TypeError("bool required")
            return not value
        return -value
    if isinstance(node, A.Binary):
        left = reference_expr(node.left, env)
        right = reference_expr(node.right, env)
        if node.op == "==":
            return q_eq(left, right)
        if node.op == "!=":
            return not q_eq(left, right)
        if node.op in ("<", ">", "<=", ">="):
            return compare(node.op, left, right)
        return arith(node.op, left, right)
    if isinstance(node, A.Ternary):
        condition = reference_expr(node.cond, env)
        if type(condition) is not bool:
            raise TypeError("bool required")
        return reference_expr(node.a if condition else node.b, env)
    raise TypeError(type(node).__name__)


def reference_program(program):
    env = {}
    result = None
    for stmt in program.body:
        if isinstance(stmt, A.Let):
            result = None
            env[stmt.name] = reference_expr(stmt.value, env) if stmt.value is not None else None
        elif isinstance(stmt, A.Assign) and isinstance(stmt.target, A.Ident) and stmt.op == "=":
            env[stmt.target.name] = reference_expr(stmt.value, env)
            result = None
        elif isinstance(stmt, A.ExprStmt):
            result = reference_expr(stmt.expr, env)
        else:
            raise TypeError(type(stmt).__name__)
    return result


class DifferentialQVMTests(unittest.TestCase):
    def test_expression_corpus_matches_reference_semantics(self):
        corpus = [
            "nil", "true", "false", "7", "1.5", '"qich"',
            "1 + 2 * 3", "9 / 3", "10 % 4", "-5",
            "1 < 2", "2 <= 2", "3 > 2", "3 >= 3",
            "true == 1", "1 == 1.0", "!false", '"q" * 3',
            '"qi" + "ch"', "true ? 7 : 9", "false ? 7 : 9",
        ]
        for source in corpus:
            with self.subTest(source=source):
                program = parse(source, "diff.qh")
                expected = reference_program(program)
                actual = execute(compile_program(program))
                self.assertEqual(actual, expected)
                self.assertIs(type(actual), type(expected))

    def test_locals_match_reference_model(self):
        program = parse("let x = 2\nx = 7\nx + 1", "diff.qh")
        self.assertEqual(execute(compile_program(program)), reference_program(program))


if __name__ == "__main__":
    unittest.main()
