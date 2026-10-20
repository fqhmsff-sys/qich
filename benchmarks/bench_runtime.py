#!/usr/bin/env python3
"""Benchmark sederhana interpreter Qich; bukan benchmark lintas mesin yang mutlak."""
import argparse
import io
import statistics
import time

from qich.compiler import parse
from qich.runtime.interp import Interp


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iterations", type=int, default=100_000)
    ap.add_argument("--repeat", type=int, default=5)
    args = ap.parse_args()
    if args.iterations < 1 or args.repeat < 1:
        ap.error("--iterations dan --repeat harus >= 1")

    source = f"let total = 0\nfor i in 0..{args.iterations} {{ total += i }}"
    start = time.perf_counter()
    program = parse(source, "<benchmark>")
    parse_ms = (time.perf_counter() - start) * 1000
    samples = []
    expected = args.iterations * (args.iterations - 1) // 2
    for _ in range(args.repeat):
        interp = Interp(out=io.StringIO())
        start = time.perf_counter()
        env = interp.run_module(program, "<benchmark>")
        samples.append(time.perf_counter() - start)
        if env.vars.get("total") != expected:
            raise SystemExit("hasil benchmark salah; runtime tidak menghasilkan total yang diharapkan")
    median = statistics.median(samples)
    print(f"Qich interpreter benchmark (Python {__import__('sys').version.split()[0]})")
    print(f"loop iterations : {args.iterations:,}")
    print(f"parse           : {parse_ms:.2f} ms")
    print(f"runtime median  : {median * 1000:.2f} ms ({args.repeat} runs)")
    print(f"iterations/sec  : {args.iterations / median:,.0f}")


if __name__ == "__main__":
    main()
