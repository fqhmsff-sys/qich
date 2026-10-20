"""Pipeline: parse -> check -> kumpulkan modul -> bundle/jalankan."""
import io
import os
import sys
from ..compiler import parse
from ..compiler import ast as A
from ..compiler.diagnostics import QichError, render_error, render_warn
from ..compiler.semantic import check_program
from ..runtime.interp import Interp
from ..runtime.loader import FileSource, BundleSource, Loader
from ..security import Policy


def make_policy(manifest=None, extra_allow=()):
    b = (manifest or {}).get("bridge", {}) or {}
    return Policy(list(b.get("allow", [])) + list(extra_allow), bool(b.get("allow_all", False)))


def check_module(prog, file, sources, err_out):
    errs, warns = check_program(prog, file)
    for w in warns: print(render_warn(w, sources), file=err_out)
    for e in errs: print(render_error(e, sources), file=err_out)
    return len(errs)


def collect(entry_file, source, err_out=sys.stderr, do_check=True):
    """Muat entry + seluruh impor mod:/pkg: (statik) -> (modules, entry_key, jumlah_error)."""
    with open(entry_file, encoding="utf-8") as f: src = f.read()
    rel = os.path.relpath(entry_file)
    prog = parse(src, rel)
    mods = {"|entry|": {"file": rel, "pkg": None, "program": prog}}
    sources = {rel: src}; nerr = 0
    queue = [("|entry|", mods["|entry|"])]
    while queue:
        key, m = queue.pop()
        if do_check: nerr += check_module(m["program"], m["file"], sources, err_out)
        for s in m["program"].body:
            if type(s) is A.Use and s.eco in ("mod", "pkg"):
                try:
                    k2, m2 = source.fetch(s.eco, s.lib, m["pkg"])
                except QichError as e:
                    e.line = e.line or s.line; e.col = e.col or s.col; e.file = e.file or m["file"]
                    print(render_error(e, sources), file=err_out); nerr += 1; continue
                if k2 not in mods:
                    mods[k2] = m2
                    try:
                        with open(m2["file"], encoding="utf-8") as f: sources[m2["file"]] = f.read()
                    except OSError: pass
                    queue.append((k2, m2))
    return mods, nerr, sources


def execute(prog, file, source, argv, policy, out=None, sources=None, call_main=True):
    I = Interp(out=out, loader=Loader(source), argv=argv, policy=policy)
    env = I.run_module(prog, file)
    if call_main:
        main = env.vars.get("main")
        if main is not None and hasattr(main, "node"):
            I.call(main, [list(argv)] if main.node.params else [])
    return I, env


def report(e, sources=None):
    print(render_error(e, sources), file=sys.stderr)
