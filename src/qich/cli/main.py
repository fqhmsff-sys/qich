"""CLI 'qh'."""
import argparse
import glob
import io
import os
import shutil
import sys
import threading
import zipapp
from .. import __version__
from ..compiler import parse, qhc
from ..compiler.diagnostics import QichError, render_error
from ..compiler.fmt import format_source
from ..compiler import doc as docgen
from ..package import manifest, lock, registry, resolver
from ..runtime.interp import Interp, QichThrow
from ..runtime.loader import FileSource, BundleSource, Loader
from ..runtime.values import Env, QFn, to_repr, to_str
from . import pipeline
from .templates import TEMPLATES


def info(msg): print(msg)
def fail(msg): print(f"error: {msg}", file=sys.stderr); return 1


def project(args_path="."):
    root = manifest.find_root(args_path)
    if root is None:
        raise QichError("tidak ada qh.toml (bukan proyek Qich)", "ManifestError", "P0001", hint="buat proyek: qh new <nama>")
    return root, manifest.load(root)


def deps_for(root):
    return resolver.ensure_deps(root, log=lambda m: print(m, file=sys.stderr))


def qh_files(root, sub):
    return sorted(glob.glob(os.path.join(root, sub, "**", "*.qh"), recursive=True))


# ------------------------------------------------------------------ commands
def cmd_new(a):
    name = a.name
    if not manifest.NAME_RE.match(os.path.basename(name)):
        return fail("nama proyek harus a-z 0-9 _ - (mulai huruf)")
    if os.path.exists(name) and os.listdir(name):
        return fail(f"direktori '{name}' sudah ada dan tidak kosong")
    files = dict(TEMPLATES[a.template])
    pname = os.path.basename(name)
    files["qh.toml"] = f'[package]\nname = "{pname}"\nversion = "0.1.0"\nentry = "src/main.qh"\n\n[dependencies]\n'
    files[".gitignore"] = "build/\n.qh/\n*.qhc\n"
    files["README.md"] = f"# {pname}\n\n```\nqh run\nqh test\nqh build\n```\n"
    for rel, content in files.items():
        p = os.path.join(name, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f: f.write(content)
    info(f"proyek '{pname}' dibuat (template: {a.template}).\n  cd {name} && qh run")
    return 0


def run_prog(a, argv_extra):
    target = a.target
    if target and target.endswith(".qhc"):
        with open(target, "rb") as f: data = f.read()
        try: mods, entry, _ = qhc.load(data)
        except ValueError as e: return fail(f"{target}: {e}")
        root = manifest.find_root(".")
        pol = pipeline.make_policy(manifest.load(root) if root else None, a.allow or ())
        m = mods[entry]
        pipeline.execute(m["program"], m["file"], BundleSource(mods), argv_extra, pol)
        return 0
    if target and target.endswith(".qh"):
        file = os.path.abspath(target)
        root = manifest.find_root(file)
        m = manifest.load(root) if root else None
        deps = deps_for(root) if root else {}
        source = FileSource(root or os.path.dirname(file), deps)
    else:
        root, m = project(".")
        file = os.path.join(root, m["package"].get("entry", "src/main.qh"))
        source = FileSource(root, deps_for(root))
    pol = pipeline.make_policy(m, a.allow or ())
    mods, nerr, sources = pipeline.collect(file, source)
    if nerr: return 1
    entry = mods["|entry|"]
    pipeline.execute(entry["program"], entry["file"], source, argv_extra, pol, sources=sources)
    return 0


def cmd_run(a, extra):
    return run_prog(a, extra)


def cmd_check(a):
    root, m = project("."); source = FileSource(root, deps_for(root)); bad = 0
    files = qh_files(root, "src") + qh_files(root, "tests")
    for f in files:
        try:
            mods, nerr, _ = pipeline.collect(f, source)
        except QichError as e:
            pipeline.report(e); nerr = 1
        bad += nerr
    info(f"{len(files)} file diperiksa, {bad} error")
    return 1 if bad else 0


def cmd_build(a):
    root, m = project("."); source = FileSource(root, deps_for(root))
    entry = os.path.join(root, m["package"].get("entry", "src/main.qh"))
    mods, nerr, _ = pipeline.collect(entry, source)
    if nerr: return 1
    os.makedirs(os.path.join(root, "build"), exist_ok=True)
    out = os.path.join(root, "build", m["package"]["name"] + ".qhc")
    data = qhc.dump(mods, "|entry|", {"name": m["package"]["name"], "version": m["package"]["version"], "qich": __version__})
    with open(out, "wb") as f: f.write(data)
    info(f"artifact: {os.path.relpath(out)} ({len(data)} byte, {len(mods)} modul)")
    return 0


def cmd_bundle(a):
    """Buat .pyz portabel (runtime + program) yang bisa dijalankan: python3 app.pyz"""
    rc = cmd_build(a)
    if rc: return rc
    root, m = project("."); name = m["package"]["name"]
    stage = os.path.join(root, "build", "_stage")
    shutil.rmtree(stage, ignore_errors=True)
    pkg_src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    shutil.copytree(pkg_src, os.path.join(stage, "qich"), ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    os.makedirs(os.path.join(stage, "qhapp"))
    open(os.path.join(stage, "qhapp", "__init__.py"), "w").close()
    shutil.copy(os.path.join(root, "build", name + ".qhc"), os.path.join(stage, "qhapp", "app.qhc"))
    with open(os.path.join(stage, "__main__.py"), "w") as f:
        f.write("import sys\nfrom qich.cli.main import run_bundle\nrun_bundle(sys.argv[1:])\n")
    out = os.path.join(root, "build", name + ".pyz")
    zipapp.create_archive(stage, out, interpreter="/usr/bin/env python3")
    shutil.rmtree(stage)
    info(f"bundle portabel: {os.path.relpath(out)}  (jalankan: python3 {os.path.relpath(out)})")
    return 0


def run_bundle(argv):
    import pkgutil
    data = pkgutil.get_data("qhapp", "app.qhc")
    mods, entry, _ = qhc.load(data)
    m = mods[entry]
    try:
        pipeline.execute(m["program"], m["file"], BundleSource(mods), argv, pipeline.make_policy(None))
    except QichError as e:
        pipeline.report(e); sys.exit(1)


def run_tests(a):
    root, m = project("."); source = FileSource(root, deps_for(root))
    pol = pipeline.make_policy(m)
    files = qh_files(root, "tests") + [f for f in qh_files(root, "src")]
    passed = failed = 0; t_files = 0
    for f in files:
        try:
            mods, nerr, sources = pipeline.collect(f, source)
        except QichError as e:
            pipeline.report(e); failed += 1; continue
        if nerr: failed += 1; continue
        prog = mods["|entry|"]["program"]
        names = [s.name for s in prog.body if type(s).__name__ == "Fn" and s.name.startswith("test_")]
        if not names: continue
        if a.filter: names = [n for n in names if a.filter in n]
        t_files += 1
        out = io.StringIO()
        I = Interp(out=out, loader=Loader(FileSource(root, deps_for(root))), policy=pol)
        try:
            env = I.run_module(prog, os.path.relpath(f))
        except QichError as e:
            pipeline.report(e, sources); failed += 1; continue
        for n in names:
            try:
                I.call(env.vars[n], [])
                passed += 1; print(f"  ok    {os.path.relpath(f)}::{n}")
            except QichError as e:
                failed += 1; print(f"  FAIL  {os.path.relpath(f)}::{n}")
                if e.file is None: e.file = os.path.relpath(f)
                print("        " + render_error(e, sources).replace("\n", "\n        "))
            except QichThrow as t:
                failed += 1; print(f"  FAIL  {os.path.relpath(f)}::{n}: throw {to_repr(t.value)}")
    info(f"\n{passed} lulus, {failed} gagal ({t_files} file uji)")
    return 1 if failed else 0


def cmd_add(a):
    root, m = project(".")
    if a.package.startswith(("py:", "js:", "c:", "cpp:")):
        eco, lib = a.package.split(":", 1)
        b = m.setdefault("bridge", {}); b.setdefault("allow", [])
        if a.package not in b["allow"]: b["allow"].append(a.package)
        manifest.save(root, m)
        info(f"izin bridge '{a.package}' dicatat di qh.toml. Qich tidak meng-install paket {eco} otomatis (keamanan supply-chain).")
        return 0
    name = a.package
    if a.path:
        dm = manifest.load(os.path.abspath(a.path)); name = dm["package"]["name"]
        m["dependencies"][name] = {"path": a.path}
    else:
        reg = resolver.registry_path(m)
        if not reg: return fail("tidak ada registry: set QH_REGISTRY=<dir> atau [registry] path di qh.toml")
        registry.check_add(reg, name, a.allow_similar)
        ver, _ = registry.resolve(reg, name, "*")
        m["dependencies"][name] = "^" + ver
    manifest.save(root, m)
    resolver.ensure_deps(root, update=True)
    info(f"dependensi '{name}' ditambahkan; qh.lock diperbarui")
    return 0


def cmd_remove(a):
    root, m = project(".")
    if a.package not in m["dependencies"]: return fail(f"'{a.package}' tidak ada di [dependencies]")
    del m["dependencies"][a.package]; manifest.save(root, m)
    resolver.ensure_deps(root, update=True)
    info(f"'{a.package}' dihapus"); return 0


def cmd_update(a):
    root, m = project("."); d = resolver.ensure_deps(root, update=True)
    info(f"{len(d)} dependensi diperbarui"); return 0


def cmd_audit(a):
    root, m = project("."); reg = resolver.registry_path(m); entries = lock.read(root); bad = 0
    if not reg: return fail("audit butuh registry (QH_REGISTRY)")
    for n, e in entries.items():
        for adv in registry.advisories(reg, n, e["version"]):
            bad += 1; print(f"RENTAN {n} {e['version']}: {adv.get('id', '?')} — {adv.get('summary', '')}")
    info(f"{len(entries)} paket diaudit, {bad} rentan"); return 1 if bad else 0


def cmd_publish(a):
    root, m = project(".")
    f = registry.publish(root, m["package"]["name"], m["package"]["version"], a.registry)
    info(f"dipublikasikan: {f}"); return 0


def cmd_fmt(a):
    root, m = project("."); changed = 0
    for f in qh_files(root, "src") + qh_files(root, "tests"):
        with open(f, encoding="utf-8") as fh: src = fh.read()
        try: new = format_source(src, os.path.relpath(f))
        except QichError as e: pipeline.report(e); return 1
        if new != src:
            changed += 1
            if a.check: print(f"perlu diformat: {os.path.relpath(f)}")
            else:
                with open(f, "w", encoding="utf-8") as fh: fh.write(new)
    info(f"{changed} file {'perlu diformat' if a.check else 'diformat'}")
    return 1 if (a.check and changed) else 0


def cmd_doc(a):
    root, m = project("."); out = os.path.join(root, "build", "doc"); os.makedirs(out, exist_ok=True)
    n = 0
    for f in qh_files(root, "src"):
        with open(f, encoding="utf-8") as fh: src = fh.read()
        md = docgen.generate(src, os.path.relpath(f, root))
        with open(os.path.join(out, os.path.relpath(f, root).replace(os.sep, "_") + ".md"), "w", encoding="utf-8") as fh: fh.write(md)
        n += 1
    info(f"dokumentasi {n} file -> {os.path.relpath(out)}"); return 0


def cmd_clean(a):
    root, m = project(".")
    for d in ("build",):
        shutil.rmtree(os.path.join(root, d), ignore_errors=True)
    info("build/ dibersihkan"); return 0


def cmd_bridges(a):
    from ..bridge import capabilities_table
    for k, name, status, caps in capabilities_table():
        on = [c for c, v in caps.items() if v]
        print(f"{k:8} {status:10} {name}" + (f"  [{', '.join(on)}]" if on else ""))
    return 0


def cmd_repl(a):
    I = Interp(); env = Env(I.builtins)
    from ..runtime.interp import ModuleCtx
    env.vars["__module__"] = ModuleCtx("<repl>")
    print(f"Qich {__version__} REPL — Ctrl+D untuk keluar"); buf = ""
    while True:
        try: line = input("qh> " if not buf else "... ")
        except EOFError: print(); return 0
        buf += line + "\n"
        if buf.count("{") + buf.count("[") + buf.count("(") > buf.count("}") + buf.count("]") + buf.count(")"): continue
        try:
            prog = parse(buf, "<repl>")
            for s in prog.body:
                if type(s).__name__ == "ExprStmt":
                    v = I.ev(s.expr, env)
                    if v is not None: print(to_repr(v))
                else:
                    I.exec_block([s], env)
        except QichError as e:
            print(render_error(e, {"<repl>": buf}))
        except QichThrow as t: print("throw:", to_repr(t.value))
        buf = ""


# ------------------------------------------------------------------ main
def build_parser():
    p = argparse.ArgumentParser(prog="qh", description="Qich — Mudah. Aman. Cepat. Induk semua library.")
    p.add_argument("--version", action="version", version=f"qh {__version__}")
    sp = p.add_subparsers(dest="cmd")
    n = sp.add_parser("new", help="buat proyek"); n.add_argument("name"); n.add_argument("--template", choices=list(TEMPLATES), default="default")
    r = sp.add_parser("run", help="jalankan proyek/file .qh/.qhc"); r.add_argument("target", nargs="?"); r.add_argument("--allow", action="append", help="izinkan bridge, mis. py:os")
    sp.add_parser("build", help="hasilkan build/<nama>.qhc")
    sp.add_parser("bundle", help="hasilkan build/<nama>.pyz portabel")
    t = sp.add_parser("test", help="jalankan test_* di tests/ dan src/"); t.add_argument("filter", nargs="?")
    ad = sp.add_parser("add", help="tambah dependensi"); ad.add_argument("package"); ad.add_argument("--path"); ad.add_argument("--allow-similar", action="store_true")
    rm = sp.add_parser("remove", help="hapus dependensi"); rm.add_argument("package")
    sp.add_parser("check", help="parse + cek semantik")
    f = sp.add_parser("fmt", help="format kode"); f.add_argument("--check", action="store_true")
    sp.add_parser("update", help="perbarui qh.lock")
    sp.add_parser("doc", help="hasilkan dokumentasi dari ///")
    sp.add_parser("clean", help="hapus build/")
    sp.add_parser("audit", help="cek kerentanan dependensi (advisory registry)")
    pb = sp.add_parser("publish", help="publikasikan ke registry lokal"); pb.add_argument("registry")
    sp.add_parser("bridges", help="daftar adapter & kapabilitas")
    sp.add_parser("repl", help="REPL")
    return p


def main(argv):
    p = build_parser()
    extra = []
    if "--" in argv:
        i = argv.index("--"); extra = argv[i + 1:]; argv = argv[:i]
    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help(); return 0
    try:
        if a.cmd == "run": return cmd_run(a, extra)
        if a.cmd == "test": return run_tests(a)
        return {"new": cmd_new, "build": cmd_build, "bundle": cmd_bundle, "add": cmd_add, "remove": cmd_remove,
                "check": cmd_check, "fmt": cmd_fmt, "update": cmd_update, "doc": cmd_doc, "clean": cmd_clean,
                "audit": cmd_audit, "publish": cmd_publish, "bridges": cmd_bridges, "repl": cmd_repl}[a.cmd](a)
    except QichError as e:
        pipeline.report(e); return 1
    except QichThrow as t:
        print(f"error: throw tidak tertangkap: {to_str(t.value)}", file=sys.stderr); return 1
    except KeyboardInterrupt:
        return 130


def entry():
    sys.setrecursionlimit(60000)
    try: threading.stack_size(512 * 1024 * 1024)
    except (ValueError, RuntimeError): pass
    res = []

    def target():
        try: res.append(main(sys.argv[1:]))
        except SystemExit as e: res.append(e.code if isinstance(e.code, int) else (0 if e.code is None else 1))
        except RecursionError: print("error: stack overflow internal", file=sys.stderr); res.append(1)
    t = threading.Thread(target=target); t.start(); t.join()
    sys.stdout.flush()
    os._exit(res[0] if res else 1) if os.environ.get("QH_FASTEXIT") else sys.exit(res[0] if res else 1)
