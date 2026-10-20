"""Pemuat modul: sumber file (proyek) dan sumber bundle (.qhc)."""
import os
import re
from ..compiler import parse
from ..compiler.diagnostics import QichError
from .values import Namespace

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


class FileSource:
    """root: dir proyek. deps: {nama: {"dir":..., "lib": "src/lib.qh"}}"""

    def __init__(self, root, deps=None):
        self.root = root; self.deps = deps or {}; self.loaded = {}

    def _src_root(self, pkg):
        if pkg is None: return os.path.join(self.root, "src")
        return os.path.join(self.deps[pkg]["dir"], "src")

    def fetch(self, kind, name, pkg):
        if not NAME_RE.match(name):
            raise QichError(f"nama modul tidak valid: {name!r}", "ImportError", "R0111")
        if kind == "mod":
            base = self._src_root(pkg)
            rel = name.replace(".", os.sep)
            cands = [os.path.join(base, rel + ".qh"), os.path.join(base, rel, "mod.qh")]
            key = f"{pkg or ''}|mod|{name}"; newpkg = pkg
        else:
            if name not in self.deps:
                raise QichError(f"paket '{name}' tidak ada di [dependencies] qh.toml", "ImportError", "R0112",
                                f"jalankan: qh add {name}")
            d = self.deps[name]
            cands = [os.path.join(d["dir"], d.get("lib", "src/lib.qh"))]
            key = f"|pkg|{name}"; newpkg = name
        if key in self.loaded:
            return key, self.loaded[key]
        for c in cands:
            real = os.path.realpath(c)
            base = os.path.realpath(self._src_root(pkg) if kind == "mod" else self.deps[name]["dir"])
            if os.path.isfile(real):
                if not (real == base or real.startswith(base + os.sep)):
                    raise QichError("modul keluar dari direktori proyek", "ImportError", "R0113")
                with open(real, encoding="utf-8") as f:
                    src = f.read()
                prog = parse(src, os.path.relpath(real))
                self.loaded[key] = {"file": os.path.relpath(real), "pkg": newpkg, "program": prog}
                return key, self.loaded[key]
        raise QichError(f"modul '{kind}:{name}' tidak ditemukan", "ImportError", "R0114",
                        "dicari di: " + ", ".join(os.path.relpath(c) for c in cands))


class BundleSource:
    def __init__(self, mods):
        self.mods = mods

    def fetch(self, kind, name, pkg):
        key = f"{pkg or ''}|mod|{name}" if kind == "mod" else f"|pkg|{name}"
        if key not in self.mods:
            raise QichError(f"modul '{kind}:{name}' tidak ada di bundle", "ImportError", "R0114")
        return key, self.mods[key]


class Loader:
    def __init__(self, source):
        self.source = source; self.cache = {}; self.stack = []

    def import_module(self, kind, name, ctx, interp):
        pkg = ctx.pkg if ctx else None
        key, m = self.source.fetch(kind, name, pkg)
        if key in self.cache:
            return self.cache[key]
        if key in self.stack:
            raise QichError(f"impor melingkar: {' -> '.join(self.stack + [key])}", "ImportError", "R0115")
        self.stack.append(key)
        try:
            env = interp.run_module(m["program"], m["file"], m.get("pkg"))
        finally:
            self.stack.pop()
        d = {k: v for k, v in env.vars.items() if not k.startswith("__")}
        ns = Namespace(name.split(".")[-1], d)
        self.cache[key] = ns
        return ns
