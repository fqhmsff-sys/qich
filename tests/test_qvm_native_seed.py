"""Smoke, rejection, and differential tests for the temporary native QVM1 seed."""
import hashlib
import json
import os
import random
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
        compile_args = [
            compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
        ]
        sanitizers = os.environ.get("QICH_NATIVE_SANITIZERS", "").strip()
        if sanitizers:
            requested = sanitizers.split(",")
            allowed = {"address", "undefined"}
            if (
                not requested
                or len(requested) != len(set(requested))
                or set(requested) - allowed
            ):
                raise RuntimeError("QICH_NATIVE_SANITIZERS hanya menerima address,undefined")
            compile_args.extend([
                "-O1", "-g", "-fno-omit-frame-pointer",
                "-fsanitize=" + ",".join(requested),
                "-fno-sanitize-recover=all",
            ])
        else:
            compile_args.append("-O2")
        compile_args.extend([
            str(source), "-lcrypto", "-ljson-c", "-o", str(cls.binary),
        ])
        subprocess.run(compile_args, check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def assert_no_sanitizer_diagnostics(self, result):
        if not os.environ.get("QICH_NATIVE_SANITIZERS"):
            return
        self.assertGreaterEqual(
            result.returncode, 0,
            "native seed terminated by signal under sanitizers: %r" % result.stderr,
        )
        self.assertNotEqual(
            result.returncode, 86,
            "native sanitizer reported a failure: %r" % result.stderr,
        )
        diagnostics = (result.stderr or "") + "\\n" + (result.stdout or "")
        for marker in (
            "AddressSanitizer", "LeakSanitizer",
            "UndefinedBehaviorSanitizer", "runtime error:",
        ):
            self.assertNotIn(
                marker, diagnostics,
                "native sanitizer diagnostic detected: %r" % diagnostics,
            )

    def run_bytes(self, data, *, path=None, timeout=None):
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
                result = subprocess.run(
                    [str(self.binary), str(path)],
                    capture_output=True, text=True, timeout=timeout,
                )
            finally:
                path.unlink(missing_ok=True)
        else:
            result = subprocess.run(
                [str(self.binary), str(path)],
                capture_output=True, text=True, timeout=timeout,
            )
        self.assert_no_sanitizer_diagnostics(result)
        return result

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
            ("ADD-13000-bit", {"constants": [(1 << 12999) - 1, 1], "code": [["CONST", 0], ["CONST", 1], ["ADD"], ["HALT"]]}),
            ("SUB", {"constants": [-7, 5], "code": [["CONST", 0], ["CONST", 1], ["SUB"], ["HALT"]]}),
            ("MUL", {"constants": [-7, 5], "code": [["CONST", 0], ["CONST", 1], ["MUL"], ["HALT"]]}),
            ("MUL-13000-bit", {"constants": [1 << 6500, 1 << 6499], "code": [["CONST", 0], ["CONST", 1], ["MUL"], ["HALT"]]}),
            ("MOD-positive-divisor", {"constants": [-5, 3], "code": [["CONST", 0], ["CONST", 1], ["MOD"], ["HALT"]]}),
            ("MOD-negative-divisor", {"constants": [5, -3], "code": [["CONST", 0], ["CONST", 1], ["MOD"], ["HALT"]]}),
            ("MOD-bigint-negative-divisor", {"constants": [-(1 << 12999) + 17, -((1 << 6500) + 3)], "code": [["CONST", 0], ["CONST", 1], ["MOD"], ["HALT"]]}),
            ("MOD-minimum-overflow-edge", {
                "constants": [-(2**63), -1],
                "code": [["CONST", 0], ["CONST", 1], ["MOD"], ["HALT"]],
            }),
            ("EQ-strict-bool-int", {"constants": [True, 1], "code": [["CONST", 0], ["CONST", 1], ["EQ"], ["HALT"]]}),
            ("EQ-string", {"constants": ["qich", "qich"], "code": [["CONST", 0], ["CONST", 1], ["EQ"], ["HALT"]]}),
            ("NE-string", {"constants": ["qich", "Qich"], "code": [["CONST", 0], ["CONST", 1], ["NE"], ["HALT"]]}),
            ("LT-string", {"constants": ["alpha", "beta"], "code": [["CONST", 0], ["CONST", 1], ["LT"], ["HALT"]]}),
            ("LE-string", {"constants": ["alpha", "alpha"], "code": [["CONST", 0], ["CONST", 1], ["LE"], ["HALT"]]}),
            ("GT-string", {"constants": ["beta", "alpha"], "code": [["CONST", 0], ["CONST", 1], ["GT"], ["HALT"]]}),
            ("GE-string", {"constants": ["beta", "beta"], "code": [["CONST", 0], ["CONST", 1], ["GE"], ["HALT"]]}),
            ("unicode-string-order", {"constants": ["é", "雪"], "code": [["CONST", 0], ["CONST", 1], ["LT"], ["HALT"]]}),
            ("unicode-supplementary-plane", {"constants": ["🙂", "🦊"], "code": [["CONST", 0], ["CONST", 1], ["LT"], ["HALT"]]}),
            ("NE", {"constants": [None, False], "code": [["CONST", 0], ["CONST", 1], ["NE"], ["HALT"]]}),
            ("LT", {"constants": [2, 3], "code": [["CONST", 0], ["CONST", 1], ["LT"], ["HALT"]]}),
            ("LE", {"constants": [3, 3], "code": [["CONST", 0], ["CONST", 1], ["LE"], ["HALT"]]}),
            ("GT", {"constants": [4, 3], "code": [["CONST", 0], ["CONST", 1], ["GT"], ["HALT"]]}),
            ("GE", {"constants": [3, 3], "code": [["CONST", 0], ["CONST", 1], ["GE"], ["HALT"]]}),
            ("CMP-bigint", {"constants": [1 << 12999, (1 << 12999) - 1], "code": [["CONST", 0], ["CONST", 1], ["GT"], ["HALT"]]}),
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
            {"constants": [1, 2], "code": [["CONST", 0], ["CONST", 1], ["DIV"], ["HALT"]]},
            {"constants": ["left", "right"], "code": [["CONST", 0], ["CONST", 1], ["ADD"], ["HALT"]]},
        ]
        for program in programs:
            with self.subTest(program=program):
                self.assertNotEqual(self.run_program(program).returncode, 0)

        oversized = {"constants": [1 << 13000], "code": [["CONST", 0], ["HALT"]]}
        body = json.dumps(
            oversized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self.assertNotEqual(self.run_bytes(envelope(body)).returncode, 0)

    def test_string_constant_output_matches_reference(self):
        program = {"constants": ["Qich λ"], "code": [["CONST", 0], ["HALT"]]}
        expected = render_value(execute_reference(program))
        result = self.run_program(program)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected + "\n")

    def test_unicode_escape_like_literal_is_preserved(self):
        program = {"constants": [r"\u03bb"], "code": [["CONST", 0], ["HALT"]]}
        expected = render_value(execute_reference(program))
        result = self.run_program(program)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected + "\n")

    def test_oversized_string_constant_is_rejected(self):
        body = b'{"code":[["CONST",0],["HALT"]],"constants":["' + b"x" * (1024 * 1024 + 1) + b'"]}'
        self.assertNotEqual(self.run_bytes(envelope(body)).returncode, 0)

    def test_invalid_utf8_string_is_rejected(self):
        body = b'{"code":[["CONST",0],["HALT"]],"constants":["' + b"\xff" + b'"]}'
        self.assertNotEqual(self.run_bytes(envelope(body)).returncode, 0)

    def test_unpaired_unicode_surrogate_is_rejected(self):
        body = b'{"code":[["CONST",0],["HALT"]],"constants":["\\ud800"]}'
        self.assertNotEqual(self.run_bytes(envelope(body)).returncode, 0)

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

    def test_integer_arithmetic_exceeds_int64_and_matches_reference(self):
        program = {
            "constants": [2**62, 4],
            "code": [["CONST", 0], ["CONST", 1], ["MUL"], ["HALT"]],
        }
        expected = render_value(execute_reference(program))
        result = self.run_program(program)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected + "\\n")

    def test_native_bigint_13000_bit_boundaries(self):
        positive = 1 << 12999
        negative = -positive
        cases = [
            {"constants": [positive], "code": [["CONST", 0], ["HALT"]]},
            {"constants": [negative], "code": [["CONST", 0], ["HALT"]]},
            {"constants": [positive], "code": [["CONST", 0], ["NEG"], ["HALT"]]},
            {"constants": [(1 << 12999) - 1, 1],
             "code": [["CONST", 0], ["CONST", 1], ["ADD"], ["HALT"]]},
        ]
        for program in cases:
            with self.subTest(code=program["code"]):
                expected = render_value(execute_reference(program))
                result = self.run_program(program)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected + "\\n")

        overflow_programs = [
            {"constants": [positive, positive],
             "code": [["CONST", 0], ["CONST", 1], ["ADD"], ["HALT"]]},
            {"constants": [1 << 6500, 1 << 6500],
             "code": [["CONST", 0], ["CONST", 1], ["MUL"], ["HALT"]]},
        ]
        for program in overflow_programs:
            with self.subTest(overflow=program):
                self.assertNotEqual(self.run_program(program).returncode, 0)

    def test_native_bigint_modulo_matches_python_sign_rule(self):
        cases = [(-5, 3), (5, -3), (-5, -3),
                 (-(1 << 12999) + 7, -((1 << 6500) + 3))]
        for left, right in cases:
            program = {
                "constants": [left, right],
                "code": [["CONST", 0], ["CONST", 1], ["MOD"], ["HALT"]],
            }
            expected = render_value(execute_reference(program))
            result = self.run_program(program)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, expected + "\\n")

    def test_noncanonical_integer_constants_are_rejected(self):
        for token in (b"-0", b"00"):
            body = b'{"code":[["CONST",0],["HALT"]],"constants":[' + token + b"]}"
            with self.subTest(token=token):
                self.assertNotEqual(self.run_bytes(envelope(body)).returncode, 0)

    def test_embedded_nul_string_matches_reference(self):
        cases = [
            {"constants": ["a\0b"], "code": [["CONST", 0], ["HALT"]]},
            {"constants": ["a\0b", "a\0c"], "code": [["CONST", 0], ["CONST", 1], ["LT"], ["HALT"]]},
            {"constants": ["a\0b", "a\0b"], "code": [["CONST", 0], ["CONST", 1], ["EQ"], ["HALT"]]},
        ]
        for program in cases:
            with self.subTest(program=program):
                expected = render_value(execute_reference(program))
                result = self.run_program(program)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected + "\n")

    def test_deterministic_malformed_payload_fuzz_smoke(self):
        rng = random.Random(0x51494348)
        baseline = encode({"constants": [1], "code": [["CONST", 0], ["HALT"]]})[70:]
        payloads = []

        for _ in range(32):
            mutated = bytearray(baseline)
            for _ in range(rng.randint(1, 4)):
                position = rng.randrange(len(mutated))
                mutated[position] = rng.randrange(256)
            payloads.append(bytes(mutated))

        atoms = [None, True, False, 0, -1, 1.5, "lambda-λ", "emoji-🙂", [], {}, 2**80]
        opcodes = ["HALT", "POP", "DUP", "NOT", "NEG", "DIV", "EVAL_PYTHON", "CONST", "JUMP"]
        for index in range(32):
            constants = [rng.choice(atoms)]
            opcode = rng.choice(opcodes)
            if opcode == "CONST":
                instruction = [opcode, rng.choice([0, 1, -1, True, "0"])]
            elif opcode == "JUMP":
                instruction = [opcode, 1]
            else:
                instruction = [opcode]
            root = {"code": [instruction, ["HALT"]], "constants": constants}
            if index % 4 == 0:
                root = {"code": [instruction, ["HALT"]]}
            elif index % 4 == 1:
                root["unexpected"] = 0
            payloads.append(json.dumps(
                root, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8"))

        for index, body in enumerate(payloads):
            with self.subTest(case=index):
                result = self.run_bytes(envelope(body), timeout=2)
                self.assertGreaterEqual(
                    result.returncode, 0,
                    "native seed terminated by signal for fuzz case %d: %r" % (index, result.stderr),
                )

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


    @unittest.skipUnless(
        os.name == "posix" and hasattr(os, "mkfifo") and hasattr(os, "O_NONBLOCK"),
        "non-blocking FIFO open is POSIX-specific",
    )
    def test_fifo_input_is_rejected_without_blocking(self):
        fifo = Path(self.temp.name) / "input.fifo"
        os.mkfifo(fifo)
        try:
            result = subprocess.run(
                [str(self.binary), str(fifo)],
                capture_output=True,
                text=True,
                timeout=2,
            )
            self.assert_no_sanitizer_diagnostics(result)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("file tidak valid", result.stderr)
        finally:
            fifo.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
