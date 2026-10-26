"""Versioned Qich Virtual Machine building blocks."""

from .bytecode import BytecodeError, decode, encode

__all__ = ["BytecodeError", "decode", "encode"]
