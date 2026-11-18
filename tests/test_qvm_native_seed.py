"""Smoke, rejection, and differential tests for the temporary native QVM1 seed."""
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from qich.qvm.bytecode import encode
from qich.qvm.vm import execute as execute_reference

ROOT = Path(__file__).resolve().parents[1]


def envelope(body):
    return b"QVM1\n" + hashlib.sha256(body).hexdigest().encode("ascii") + b"\n" + body


def render_value(value):
    if value is None:
        return "nil"
    if type(value) is bool:
        return "true" if value else "false"
    return str(value)


class NativeQVMSeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        if not compiler:
            raise RuntimeError("native QVM seed tests require a C compiler")
        cls.temp = tempfile.TemporaryDirectory(prefix="qich-qvm-seed-")
        cls.binary = Path(cls.temp.name) / "qvm1-seed"
        source = ROOT / "bootstrap" / "native" / "qvm1_seed.c"
        subprocess.run([
            compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
            str(source), "-lcrypto", "-ljson-c", "-o", str(cls.binary),
        ], check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_bytes(self, data, *, path=None):
        if path is None:
            handle = tempfile.NamedTemporaryFile(dir=self.temp.name, delete=False)
            path = Path(handle.name)
            try:
                handle.write(data)
                handle.close()
            finally:
                if not handle.closed:
                    handle.close()
            try:
                return subprocess.run([str(self.binary), str(path)], capture_output=True, text=True)
            finally:
                path.unlink(missing_ok=True)
        return subprocess.run([str(self.binary), str(path)], capture_output=True, text=True)

    def run_program(self, program):
        return self.run_bytes(encode(program))

    def test_integer_arithmetic_and_locals(self):
        cases = [
            ({"constants": [7, 5], "code": [["CONST", 0], ["CONST", 1], ["ADD"], ["HALT"]]}, "12"),
            ({"constants": [7, 5], "code": [["CONST", 0], ["STORE_LOCAL", 0], ["LOAD_LOCAL", 0], ["CONST", 1], ["SUB"], ["HALT"]]}, "2"),
            ({"constants": [7, 5], "code": [["CONST", 0], ["CONST", 1], ["MUL"], ["HALT"]]}, "35"),
            ({"constants": [-5, 3], "code": [["CONST", 0], ["CONST", 1], ["MOD"], ["HALT"]]}, "1"),
            ({"constants": [True, 1], "code": [["CONST", 0], ["CONST", 1], ["EQ"], ["HALT"]]}, "false"),
            ({"constants": [None, None], "code": [["CONST", 0], ["CONST", 1], ["EQ"], ["HALT"]]}, "true"),
        ]
        for program, expected in cases:
            with self.subTest(program=program):
                result = self.run_program(program)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected + "\n")

    def test_native_supported_subset_matches_reference_executor(self):
        cases = [
            ("CONST", {"constants": [7], "code": [["CONST", 0], ["HALT"]]}),
            ("POP", {"constants": [7], "code": [["CONST", 0], ["POP"], ["HALT"]]}),
            ("DUP", {"constants": [7], "code": [["CONST", 0], ["DUP"], ["POP"], ["HALT"]]}),
            ("LOAD_LOCAL/STORE_LOCAL", {
                "constants": [17],
                "code": [["CONST", 0], ["STORE_LOCAL", 12], ["LOAD_LOCAL", 12], ["HALT"]],
            }),
            ("ADD", {"constants": [-7, 5], "code": [["CONST", 0], ["CONST", 1], ["ADD"], ["HALT"]]}),
            ("SUB", {"constants": [-7, 5], "code": [["CONST", 0], ["CONST", 1], ["SUB"], ["HALT"]]}),
            ("MUL", {"constants": [-7, 5], "code": [["CONST", 0], ["CONST", 1], ["MUL"], ["HALT"]]}),
            ("MOD-positive-divisor", {"constants": [-5, 3], "code": [["CONST", 0], ["CONST", 1], ["MOD"], ["HALT"]]}),
            ("MOD-negative-divisor", {"constants": [5, -3], "code": [["CONST", 0], ["CONST", 1], ["MOD"], ["HALT"]]}),
            ("MOD-minimum-overflow-edge", {
                "constants": [-(2**63), -1],
                "code": [["CONST", 0], ["CONST", 1], ["MOD"], ["HALT"]],
            }),
            ("EQ-strict-bool-int", {"constants": [True, 1], "code": [["CONST", 0], ["CONST", 1], ["EQ"], ["HALT"]]}),
            ("NE", {"constants": [None, False], "code": [["CONST", 0], ["CONST", 1], ["NE"], ["HALT"]]}),
            ("LT", {"constants": [2, 3], "code": [["CONST", 0], ["CONST", 1], ["LT"], ["HALT"]]}),
            ("LE", {"constants": [3, 3], "code": [["CONST", 0], ["CONST", 1], ["LE"], ["HALT"]]}),
            ("GT", {"constants": [4, 3], "code": [["CONST", 0], ["CONST", 1], ["GT"], ["HALT"]]}),
            ("GE", {"constants": [3, 3], "code": [["CONST", 0], ["CONST", 1], ["GE"], ["HALT"]]}),
            ("NOT", {"constants": [False], "code": [["CONST", 0], ["NOT"], ["HALT"]]}),
            ("NEG", {"constants": [7], "code": [["CONST", 0], ["NEG"], ["HALT"]]}),
            ("JUMP", {"constants": [1, 9], "code": [["JUMP", 2], ["CONST", 0], ["CONST", 1], ["HALT"]]}),
            ("JUMP_IF_FALSE-true", {
                "constants": [True, 7, 9],
                "code": [["CONST", 0], ["JUMP_IF_FALSE", 4], ["CONST", 1], ["JUMP", 5], ["CONST", 2], ["HALT"]],
            }),
            ("JUMP_IF_FALSE-false", {
                "constants": [False, 7, 9],
                "code": [["CONST", 0], ["JUMP_IF_FALSE", 4], ["CONST", 1], ["JUMP", 5], ["CONST", 2], ["HALT"]],
            }),
            ("HALT", {"constants": [11, 99], "code": [["CONST", 0], ["HALT"], ["CONST", 1]]}),
            ("empty-program", {"constants": [], "code": []}),
        ]
        for opcode, program in cases:
            with self.subTest(opcode=opcode):
                expected = render_value(execute_reference(program))
                result = self.run_program(program)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected + "\n")

    def test_boolean_control_flow_and_empty_program(self):
        program = {
            "constants": [False, 7, 9],
            "code": [["CONST", 0], ["JUMP_IF_FALSE", 4], ["CONST", 1], ["JUMP", 5], ["CONST", 2], ["HALT"]],
        }
        result = self.run_program(program)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "9\n")
        empty = self.run_program({"constants": [], "code": []})
        self.assertEqual(empty.returncode, 0, empty.stderr)
        self.assertEqual(empty.stdout, "nil\n")

    def test_checksum_tampering_is_rejected(self):
        data = bytearray(encode({"constants": [1], "code": [["CONST", 0], ["HALT"]]}))
        data[-1] ^= 1
        self.assertNotEqual(self.run_bytes(bytes(data)).returncode, 0)

    def test_unsupported_qvm1_values_and_opcodes_fail_closed(self):
        programs = [
            {"constants": [1.5], "code": [["CONST", 0], ["HALT"]]},
            {"constants": ["text"], "code": [["CONST", 0], ["HALT"]]},
            {"constants": [1, 2], "code": [["CONST", 0], ["CONST", 1], ["DIV"], ["HALT"]]},
            {"constants": [2**63], "code": [["CONST", 0], ["HALT"]]},
        ]
        for program in programs:
            with self.subTest(program=program):
                self.assertNotEqual(self.run_program(program).returncode, 0)

    def test_duplicate_json_keys_and_boolean_operands_are_rejected(self):
        bodies = [
            b'{"code":[],"code":[],"constants":[]}',
            b'{"code":[["CONST",true],["HALT"]],"constants":[1]}',
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.assertNotEqual(self.run_bytes(envelope(body)).returncode, 0)

    def test_unknown_opcode_and_static_stack_underflow_are_rejected(self):
        bodies = [
            b'{"code":[["EVAL_PYTHON"]],"constants":[]}',
            b'{"code":[["POP"],["HALT"]],"constants":[]}',
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.assertNotEqual(self.run_bytes(envelope(body)).returncode, 0)

    def test_uninitialized_local_and_infinite_loop_are_rejected(self):
        uninitialized = {"constants": [], "code": [["LOAD_LOCAL", 0], ["HALT"]]}
        infinite = {"constants": [], "code": [["JUMP", 0]]}
        self.assertNotEqual(self.run_program(uninitialized).returncode, 0)
        self.assertNotEqual(self.run_program(infinite).returncode, 0)

    def test_integer_overflow_is_rejected(self):
        program = {"constants": [2**62, 4], "code": [["CONST", 0], ["CONST", 1], ["MUL"], ["HALT"]]}
        self.assertNotEqual(self.run_program(program).returncode, 0)
        minimum_modulo = {"constants": [-(2**63), -1], "code": [["CONST", 0], ["CONST", 1], ["MOD"], ["HALT"]]}
        result = self.run_program(minimum_modulo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "0\n")

    @unittest.skipUnless(os.name == "posix", "O_NOFOLLOW is POSIX-specific")
    def test_symlink_input_is_rejected(self):
        target = Path(self.temp.name) / "target.qvm"
        link = Path(self.temp.name) / "link.qvm"
        target.write_bytes(encode({"constants": [1], "code": [["CONST", 0], ["HALT"]]}))
        link.symlink_to(target)
        try:
            self.assertNotEqual(self.run_bytes(b"", path=link).returncode, 0)
        finally:
            link.unlink(missing_ok=True)
            target.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
