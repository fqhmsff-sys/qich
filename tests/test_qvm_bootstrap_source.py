import os
import unittest

from helpers import ROOT, run
from qich.compiler.diagnostics import QichError
from qich.qvm.vm import execute
from qich.runtime.values import to_str


def qich_literal(value):
    if value is None:
        return "nil"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is str:
        import json
        return json.dumps(value, ensure_ascii=False)
    if type(value) in (int, float):
        return repr(value)
    if type(value) is list:
        return "[" + ", ".join(qich_literal(item) for item in value) + "]"
    if type(value) is dict:
        return "{" + ", ".join(
            qich_literal(key) + ": " + qich_literal(item)
            for key, item in value.items()
        ) + "}"
    raise TypeError(type(value).__name__)


class QichSourceQVMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(ROOT, "bootstrap", "qvm1.qh")
        with open(path, encoding="utf-8") as stream:
            cls.bootstrap_source = stream.read()

    def qich_execute(self, program, max_steps=1000000, max_stack=65536):
        source = (
            self.bootstrap_source
            + "\nlet _program = " + qich_literal(program)
            + "\nprint(qvm1_execute(_program, " + str(max_steps) + ", " + str(max_stack) + "))\n"
        )
        return run(source).rstrip("\n")

    def test_qich_source_executor_matches_reference_corpus(self):
        corpus = [
            {
                "constants": [7, 5, 2],
                "code": [
                    ["CONST", 0], ["CONST", 1], ["ADD"],
                    ["CONST", 2], ["MUL"], ["CONST", 0], ["GT"], ["HALT"],
                ],
            },
            {
                "constants": [False, "wrong", "right"],
                "code": [
                    ["CONST", 0], ["JUMP_IF_FALSE", 4],
                    ["CONST", 1], ["JUMP", 5], ["CONST", 2], ["HALT"],
                ],
            },
            {
                "constants": [7, 3],
                "code": [
                    ["CONST", 0], ["STORE_LOCAL", 0],
                    ["LOAD_LOCAL", 0], ["CONST", 1], ["ADD"], ["HALT"],
                ],
            },
            {
                "constants": ["q", 3],
                "code": [["CONST", 0], ["CONST", 1], ["MUL"], ["HALT"]],
            },
            {
                "constants": [True, 9, 4],
                "code": [
                    ["CONST", 0], ["JUMP_IF_FALSE", 4],
                    ["CONST", 1], ["JUMP", 5], ["CONST", 2], ["HALT"],
                ],
            },
        ]
        for program in corpus:
            with self.subTest(program=program):
                self.assertEqual(
                    self.qich_execute(program),
                    to_str(execute(program)),
                )

    def test_qich_source_verifier_rejects_static_stack_underflow(self):
        with self.assertRaises(QichError):
            self.qich_execute({"constants": [], "code": [["POP"], ["HALT"]]})

    def test_qich_source_executor_enforces_step_budget(self):
        with self.assertRaises(QichError):
            self.qich_execute({"constants": [], "code": [["JUMP", 0]]}, max_steps=10)

    def test_qich_source_executor_rejects_uninitialized_local(self):
        with self.assertRaises(QichError):
            self.qich_execute({"constants": [], "code": [["LOAD_LOCAL", 0], ["HALT"]]})

    def test_qich_source_executor_rejects_unknown_opcode(self):
        with self.assertRaises(QichError):
            self.qich_execute({"constants": [], "code": [["EVAL_PYTHON"]]})
