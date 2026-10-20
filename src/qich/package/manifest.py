import os
import re
import tomllib
from ..compiler.diagnostics import QichError

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
RESERVED = {"std", "qy", "chyb", "qapp", "qich", "qh", "mod", "pkg", "main", "test", "core"}


def find_root(start="."):
    d = os.path.abspath(start)
    if os.path.isfile(d): d = os.path.dirname(d)
    while True:
        if os.path.isfile(os.path.join(d, "qh.toml")): return d
        p = os.path.dirname(d)
        if p == d: return None
        d = p


def load(root):
    path = os.path.join(root, "qh.toml")
    try:
        with open(path, "rb") as f: m = tomllib.load(f)
    except FileNotFoundError:
        raise QichError(f"qh.toml tidak ditemukan di {root}", "ManifestError", "P0001")
    except tomllib.TOMLDecodeError as e:
        raise QichError(f"qh.toml tidak valid: {e}", "ManifestError", "P0002", file=path)
    pk = m.get("package")
    if not isinstance(pk, dict) or not isinstance(pk.get("name"), str) or not isinstance(pk.get("version"), str):
        raise QichError("[package] wajib punya name dan version (string)", "ManifestError", "P0003", file=path)
    if not NAME_RE.match(pk["name"]):
        raise QichError(f"nama paket tidak valid: {pk['name']!r} (a-z 0-9 _ -, mulai huruf)", "ManifestError", "P0004", file=path)
    if not re.match(r"^\d+\.\d+\.\d+$", pk["version"]):
        raise QichError("version harus berbentuk X.Y.Z", "ManifestError", "P0005", file=path)
    m.setdefault("dependencies", {})
    for k, v in m["dependencies"].items():
        if not (isinstance(v, str) or (isinstance(v, dict) and isinstance(v.get("path"), str))):
            raise QichError(f"dependensi '{k}' tidak valid: gunakan \"versi\" atau {{ path = \"...\" }}", "ManifestError", "P0006", file=path)
    m.setdefault("bridge", {})
    return m


def _q(s): return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def dump(m):
    out = ["[package]"]
    for k, v in m["package"].items(): out.append(f"{k} = {_q(v)}")
    out.append("\n[dependencies]")
    for k, v in sorted(m.get("dependencies", {}).items()):
        out.append(f"{k} = {{ path = {_q(v['path'])} }}" if isinstance(v, dict) else f"{k} = {_q(v)}")
    b = m.get("bridge") or {}
    if b:
        out.append("\n[bridge]")
        if "allow" in b: out.append("allow = [" + ", ".join(_q(x) for x in b["allow"]) + "]")
        if "allow_all" in b: out.append(f"allow_all = {'true' if b['allow_all'] else 'false'}")
    reg = m.get("registry")
    if reg:
        out.append("\n[registry]")
        for k, v in reg.items(): out.append(f"{k} = {_q(v)}")
    return "\n".join(out) + "\n"


def save(root, m):
    with open(os.path.join(root, "qh.toml"), "w", encoding="utf-8") as f: f.write(dump(m))
