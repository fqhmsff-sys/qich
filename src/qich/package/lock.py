import hashlib
import os
import tomllib

SKIP = {".qh", "build", ".git", "__pycache__", "qh.lock"}


def pkg_hash(d):
    h = hashlib.sha256()
    for base, dirs, files in os.walk(d):
        dirs[:] = sorted(x for x in dirs if x not in SKIP)
        for fn in sorted(files):
            if fn in SKIP or fn.endswith(".pyc"): continue
            p = os.path.join(base, fn)
            if os.path.islink(p): continue
            rel = os.path.relpath(p, d).replace(os.sep, "/")
            h.update(rel.encode() + b"\0")
            with open(p, "rb") as f: h.update(hashlib.sha256(f.read()).digest())
    return h.hexdigest()


def read(root):
    p = os.path.join(root, "qh.lock")
    if not os.path.isfile(p): return {}
    with open(p, "rb") as f: d = tomllib.load(f)
    return {e["name"]: e for e in d.get("package", [])}


def write(root, entries):
    out = ["# Dihasilkan oleh qh. Jangan ubah manual.", "version = 1"]
    for name in sorted(entries):
        e = entries[name]
        out.append("\n[[package]]")
        for k in ("name", "version", "source", "sha256", "archive_sha256"):
            if k in e: out.append(f'{k} = "{e[k]}"')
    with open(os.path.join(root, "qh.lock"), "w", encoding="utf-8") as f: f.write("\n".join(out) + "\n")
