"""Regression tests for the versioned QVM bytecode envelope."""
import unittest

from qich.qvm.bytecode import BytecodeError, decode, encode


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
            decode(blob.replace(b"QVM1\n", b"QVM9\n", 1))

    def test_invalid_opcode_is_rejected(self):
        with self.assertRaises(BytecodeError):
            encode({"constants": [], "code": [["EVAL_PYTHON"]]})

    def test_resource_limits_are_enforced(self):
        with self.assertRaises(BytecodeError):
            encode({"constants": [], "code": [["HALT"]] * 100001})


if __name__ == "__main__":
    unittest.main()
