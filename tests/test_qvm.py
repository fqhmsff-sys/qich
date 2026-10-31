"""Regression tests for the versioned QVM bytecode envelope and executor."""
import unittest

from qich.qvm.bytecode import BytecodeError, decode, encode
from qich.qvm.vm import VMError, execute
from qich.qvm.compiler import CompileError, compile_program
from qich.compiler import parse


class QVMBytecodeTests(unittest.TestCase):
    def test_round_trip_is_deterministic(self):
        program = {
            "constants": [None, True, 7, 1.5, "qich"],
            "code": [["CONST", 2], ["CONST", 4], ["HALT"]],
        }
        first = encode(program)
        self.assertEqual(first, encode(program))
        self.assertEqual(decode(first), program)

    def test_corruption_is_rejected(self):
        blob = bytearray(encode({"constants": [1], "code": [["HALT"]]}))
        blob[-1] ^= 1
        with self.assertRaises(BytecodeError):
            decode(bytes(blob))

    def test_unknown_version_is_rejected(self):
        blob = encode({"constants": [], "code": [["HALT"]]})
        with self.assertRaises(BytecodeError):
            decode(blob.replace(b"QVM1
", b"QVM9
", 1))

    def test_invalid_opcode_is_rejected(self):
        with self.assertRaises(BytecodeError):
            encode({"constants": [], "code": [["EVAL_PYTHON"]]})

    def test_resource_limits_are_enforced(self):
        with self.assertRaises(BytecodeError):
            encode({"constants": [], "code": [["HALT"]] * 100001})


class QVMExecutorTests(unittest.TestCase):
    def test_arithmetic_and_comparison(self):
        program = {
            "constants": [7, 5, 2],
            "code": [
                ["CONST", 0], ["CONST", 1], ["ADD"],
                ["CONST", 2], ["MUL"], ["CONST", 0], ["GT"], ["HALT"],
            ],
        }
        self.assertIs(execute(program), True)

    def test_conditional_jump(self):
        program = {
            "constants": [False, "wrong", "right"],
            "code": [
                ["CONST", 0], ["JUMP_IF_FALSE", 4],
                ["CONST", 1], ["JUMP", 5], ["CONST", 2], ["HALT"],
            ],
        }
        self.assertEqual(execute(program), "right")

    def test_stack_underflow_is_rejected(self):
        with self.assertRaises(VMError):
            execute({"constants": [], "code": [["POP"], ["HALT"]]})

    def test_step_budget_stops_infinite_loop(self):
        with self.assertRaises(VMError):
            execute({"constants": [], "code": [["JUMP", 0]]}, max_steps=20)

    def test_stack_budget_is_enforced(self):
        program = {"constants": [1], "code": [["CONST", 0], ["CONST", 0], ["HALT"]]}
        with self.assertRaises(VMError):
            execute(program, max_stack=1)

    def test_invalid_budget_is_rejected(self):
        program = {"constants": [], "code": [["HALT"]]}
        for value in (0, -1, True, 1.5):
            with self.assertRaises(VMError):
                execute(program, max_steps=value)

    def test_arithmetic_failure_is_wrapped(self):
        program = {
            "constants": [1, 0],
            "code": [["CONST", 0], ["CONST", 1], ["DIV"], ["HALT"]],
        }
        with self.assertRaises(VMError):
            execute(program)


if __name__ == "__main__":
    unittest.main()
