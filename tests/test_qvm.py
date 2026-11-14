"""Regression tests for the versioned QVM bytecode envelope and executor."""
import hashlib
import random
import unittest
from unittest.mock import patch

from qich.compiler import parse
from qich.qvm.bytecode import (
    BytecodeError, MAGIC, MAX_INTEGER_BITS, MAX_STACK, MAX_STRING, decode, encode,
)
from qich.qvm.compiler import CompileError, compile_program
from qich.qvm.vm import VMError, execute, prepare
import qich.qvm.vm as qvm_vm


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

    def test_duplicate_json_keys_are_rejected(self):
        body = b'{"constants":[],"constants":[1],"code":[["HALT"]]}'
        digest = hashlib.sha256(body).hexdigest().encode("ascii")
        with self.assertRaises(BytecodeError):
            decode(MAGIC + digest + b"\n" + body)

    def test_invalid_unicode_constant_is_rejected(self):
        with self.assertRaises(BytecodeError):
            encode({"constants": ["\ud800"], "code": [["HALT"]]})

    def test_excessively_nested_json_is_rejected_cleanly(self):
        body = (
            b'{"constants":' + b"[" * 2000 + b"0" + b"]" * 2000
            + b',"code":[["HALT"]]}'
        )
        digest = hashlib.sha256(body).hexdigest().encode("ascii")
        with self.assertRaises(BytecodeError):
            decode(MAGIC + digest + b"\n" + body)

    def test_seeded_malformed_payload_corpus_never_leaks_parser_errors(self):
        rng = random.Random(20261102)
        for _ in range(128):
            body = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 96)))
            digest = hashlib.sha256(body).hexdigest().encode("ascii")
            blob = MAGIC + digest + b"\n" + body
            try:
                decode(blob)
            except BytecodeError:
                pass

    def test_non_finite_and_oversized_constants_are_rejected(self):
        for value in (float("nan"), float("inf"), 1 << MAX_INTEGER_BITS):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(BytecodeError):
                    encode({"constants": [value], "code": [["HALT"]]})


class QVMPreparedProgramTests(unittest.TestCase):
    def test_prepare_snapshots_and_freezes_program(self):
        source = {
            "constants": [7],
            "code": [["CONST", 0], ["HALT"]],
        }
        prepared = prepare(source)
        source["constants"][0] = 99
        source["code"][0][1] = 0
        self.assertEqual(execute(prepared), 7)
        self.assertEqual(execute(source), 99)
        with self.assertRaises((AttributeError, TypeError)):
            prepared.code[0][1] = 1
        with self.assertRaises((AttributeError, TypeError)):
            prepared.constants = (99,)

    def test_prepared_and_validated_execution_match(self):
        program = {
            "constants": [4, 3],
            "code": [["CONST", 0], ["CONST", 1], ["ADD"], ["HALT"]],
        }
        prepared = prepare(program)
        self.assertEqual(execute(prepared), execute(program))
        self.assertEqual(execute(prepared, max_steps=4), 7)
        with self.assertRaises(VMError):
            execute(prepared, max_steps=2)

    def test_prepare_rejects_invalid_bytecode(self):
        with self.assertRaises(VMError):
            prepare({"constants": [], "code": [["UNKNOWN_OPCODE"]]})

    def test_prepare_rejects_non_list_program_sections(self):
        with self.assertRaises(VMError):
            prepare({"constants": (), "code": [["HALT"]]})

    def test_one_shot_execution_uses_the_validated_snapshot(self):
        source = {
            "constants": [7],
            "code": [["CONST", 0], ["HALT"]],
        }
        validate = qvm_vm._validate

        def mutate_caller_program_after_validation(candidate):
            validate(candidate)
            source["code"][0][1] = 99

        with patch.object(
            qvm_vm, "_validate",
            side_effect=mutate_caller_program_after_validation,
        ):
            self.assertEqual(qvm_vm.execute(source), 7)
        self.assertEqual(source["code"][0][1], 99)


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

    def test_static_stack_underflow_is_rejected(self):
        with self.assertRaises(VMError):
            execute({"constants": [], "code": [["POP"], ["HALT"]]})

    def test_control_flow_join_requires_equal_stack_height(self):
        program = {
            "constants": [True, 1],
            "code": [
                ["CONST", 0], ["JUMP_IF_FALSE", 4],
                ["CONST", 1], ["JUMP", 5],
                ["JUMP", 5], ["HALT"],
            ],
        }
        with self.assertRaises(BytecodeError):
            encode(program)

    def test_stack_growth_loop_is_rejected(self):
        program = {"constants": [1], "code": [["CONST", 0], ["JUMP", 0]]}
        with self.assertRaises(BytecodeError):
            encode(program)

    def test_static_stack_ceiling_is_enforced(self):
        program = {
            "constants": [1],
            "code": [["CONST", 0]] * (MAX_STACK + 1) + [["HALT"]],
        }
        with self.assertRaises(BytecodeError):
            encode(program)

    def test_dup_has_correct_static_stack_effect(self):
        program = {
            "constants": [7],
            "code": [["CONST", 0], ["DUP"], ["ADD"], ["HALT"]],
        }
        self.assertEqual(execute(program), 14)

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

    def test_string_repeat_is_bounded(self):
        self.assertEqual(execute(compile_program(parse('"q" * 3'))), "qqq")
        program = {
            "constants": ["x" * MAX_STRING, 2],
            "code": [["CONST", 0], ["CONST", 1], ["MUL"], ["HALT"]],
        }
        with self.assertRaises(VMError):
            execute(program)


class QVMCompilerRegressionTests(unittest.TestCase):
    def _run(self, source):
        return execute(compile_program(parse(source, "qvm-regression.qh")))

    def test_locals_compile_and_execute(self):
        self.assertEqual(self._run("let x = 2\nx = 7\nx + 1"), 8)

    def test_constant_pool_deduplicates_by_type(self):
        program = compile_program(parse("1 + 1\ntrue == 1", "qvm-regression.qh"))
        self.assertEqual(len(program["constants"]), 2)
        self.assertIs(type(program["constants"][0]), int)
        self.assertIs(type(program["constants"][1]), bool)

    def test_constant_pool_handles_many_unique_literals(self):
        source = "\n".join(str(i) for i in range(2048))
        program = compile_program(parse(source, "qvm-constant-pool.qh"))
        self.assertEqual(len(program["constants"]), 2048)

    def test_uninitialized_local_bytecode_fails_closed(self):
        with self.assertRaises(VMError):
            execute({"constants": [], "code": [["LOAD_LOCAL", 0], ["HALT"]]})

    def test_conditions_require_bool(self):
        with self.assertRaises(VMError):
            self._run("1 ? 2 : 3")
        with self.assertRaises(VMError):
            execute({"constants": [1], "code": [["CONST", 0], ["NOT"], ["HALT"]]})

    def test_local_slot_bounds_are_verified(self):
        with self.assertRaises(BytecodeError):
            encode({"constants": [], "code": [["LOAD_LOCAL", 100000], ["HALT"]]})

    def test_typed_let_fails_closed_until_annotation_checks_exist(self):
        with self.assertRaises(CompileError):
            compile_program(parse("let x: int = 1", "qvm-regression.qh"))


    def test_short_circuit_boolean_operators(self):
        self.assertIs(self._run("false && (1 / 0 > 0)"), False)
        self.assertIs(self._run("true || (1 / 0 > 0)"), True)
        self.assertIs(self._run("true && false"), False)
        self.assertIs(self._run("false || true"), True)

    def test_logical_operators_require_boolean_operands(self):
        with self.assertRaises(VMError):
            self._run("true && 1")
        with self.assertRaises(VMError):
            self._run("1 || true")


class QVMSemanticHardeningTests(unittest.TestCase):
    def _run(self, source):
        return execute(compile_program(parse(source, "qvm-hardening.qh")))

    def test_equality_matches_qich_bool_and_numeric_rules(self):
        self.assertIs(self._run("true == 1"), False)
        self.assertIs(self._run("1 == 1.0"), True)

    def test_boolean_is_not_a_number(self):
        for source in ("true + 1", "true * 3", "true < 2", "-true"):
            with self.subTest(source=source):
                with self.assertRaises(VMError):
                    self._run(source)


if __name__ == "__main__":
    unittest.main()
