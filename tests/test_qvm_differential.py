"""Differential checks between the Qich reference semantics and QVM subset."""
import unittest

from qich.compiler import parse
from qich.qvm.compiler import compile_program
from qich.qvm.vm import execute
from qich.runtime.interp import arith, compare


def reference_expr(node, env=None):
    """Evaluate only the capability-free subset accepted by the QVM compiler."""
    from qich.compiler import ast as A
    env = {} if env is None else env
    if isinstance(node, A.Num): return node.value
    if isinstance(node, A.Str): return node.value
    if isinstance(node, A.Bool): return node.value
    if isinstance(node, A.Nil): return None
    if isinstance(node, A.Ident): return env[node.name]
    if isinstance(node, A.Unary):
        v = reference_expr(node.operand, env)
        if node.op == "!":
            if type(v) is not bool: raise TypeError("bool required")
            return not v
        return -v
    if isinstance(node, A.Binary):
        a = reference_expr(node.left, env); b = reference_expr(node.right, env)
        if node.op == "==": return type(a) is type(b) and a == b
        if node.op == "!=": return not (type(a) is type(b) and a == b)
        if node.op in ("<", ">", "<=", ">="): return compare(node.op, a, b)
        return arith(node.op, a, b)
    if isinstance(node, A.Ternary):
        cond = reference_expr(node.cond, env)
        if type(cond) is not bool: raise TypeError("bool required")
        return reference_expr(node.a if cond else node.b, env)
    raise TypeError(type(node).__name__)


class DifferentialQVMTests(unittest.TestCase):
    def test_expression_corpus_matches_reference_semantics(self):
        corpus = [
            "nil", "true", "false", "7", "1.5", '"qich"',
            "1 + 2 * 3", "9 / 3", "10 % 4", "-5",
            "1 < 2", "2 <= 2", "3 > 2", "3 >= 3",
            '"qi" + "ch"', "true ? 7 : 9", "false ? 7 : 9",
        ]
        for source in corpus:
            with self.subTest(source=source):
                ast = parse(source, "diff.qh")
                expected = reference_expr(ast.body[0].expr)
                actual = execute(compile_program(ast))
                self.assertEqual(actual, expected)
                self.assertIs(type(actual), type(expected))

    def test_locals_match_reference_model(self):
        ast = parse("let x = 2\nx = 7\nx + 1", "diff.qh")
        self.assertEqual(execute(compile_program(ast)), 8)


if __name__ == "__main__":
    unittest.main()
