#!/usr/bin/env python3
"""Measure QVM1 parsing, constant-pool compilation, and compiler peak memory."""
import argparse
import statistics
import sys
import time
import tracemalloc

from qich.compiler import parse
from qich.qvm import compile_program, encode, execute, prepare
from qich.qvm.bytecode import MAX_INSTRUCTIONS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--constants", type=int, default=10000)
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args()
    if args.constants < 1 or args.repeat < 1:
        parser.error("--constants dan --repeat harus >= 1")
    if args.constants * 2 > MAX_INSTRUCTIONS:
        parser.error("jumlah constant melebihi batas instruction QVM1")

    source = "\n".join('"qich-%d"' % i for i in range(args.constants))
    started = time.perf_counter()
    program = parse(source, "<qvm-benchmark>")
    parse_ms = (time.perf_counter() - started) * 1000

    samples = []
    compiled = None
    for _ in range(args.repeat):
        started = time.perf_counter()
        compiled = compile_program(program)
        samples.append(time.perf_counter() - started)

    tracemalloc.start()
    compile_program(program)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    expected = "qich-%d" % (args.constants - 1)
    if len(compiled["constants"]) != args.constants or execute(compiled) != expected:
        raise SystemExit("hasil benchmark QVM salah")

    prepare_started = time.perf_counter()
    prepared = prepare(compiled)
    prepare_ms = (time.perf_counter() - prepare_started) * 1000

    runtime_samples = []
    prepared_runtime_samples = []
    for _ in range(args.repeat):
        started = time.perf_counter()
        actual = execute(compiled)
        runtime_samples.append(time.perf_counter() - started)
        if actual != expected:
            raise SystemExit("hasil eksekusi QVM berubah selama benchmark")

        started = time.perf_counter()
        prepared_actual = execute(prepared)
        prepared_runtime_samples.append(time.perf_counter() - started)
        if prepared_actual != expected:
            raise SystemExit("hasil prepared QVM berubah selama benchmark")

    compile_median = statistics.median(samples)
    runtime_median = statistics.median(runtime_samples)
    prepared_runtime_median = statistics.median(prepared_runtime_samples)
    artifact_size = len(encode(compiled))
    print("QVM1 compiler/runtime benchmark (Python %s)" % sys.version.split()[0])
    print("unique constants : %s" % format(args.constants, ","))
    print("parse            : %.2f ms" % parse_ms)
    print("compile median   : %.2f ms (%d runs)" % (compile_median * 1000, args.repeat))
    print("constants/sec    : %.0f" % (args.constants / compile_median))
    print("prepare/verify   : %.2f ms (one-time snapshot)" % prepare_ms)
    print("runtime median   : %.2f ms (%d runs, validate each call)" % (runtime_median * 1000, args.repeat))
    print("prepared runtime : %.2f ms (%d runs, verify once)" % (prepared_runtime_median * 1000, args.repeat))
    print("validated instructions/sec : %.0f" % (len(compiled["code"]) / runtime_median))
    print("prepared instructions/sec : %.0f" % (len(prepared["code"]) / prepared_runtime_median))
    print("bytecode artifact: %s bytes" % format(artifact_size, ","))
    print("compile peak     : %s bytes (tracemalloc)" % format(peak_bytes, ","))


if __name__ == "__main__":
    main()
