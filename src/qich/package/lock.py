import hashlib
import os
import stat
import tomllib
from ..compiler.diagnostics import QichError

SKIP = {".qh", "build", ".git", "__pycache__", "qh.lock"}


def pkg_hash(d):
    """Hash regular package files; reject links and special files before copying."""
    root = os.path.realpath(d)
    try:
        root_info = os.lstat(root)
    except OSError as exc:
        raise QichError("direktori paket tidak dapat diperiksa", "SecurityError", "P0152") from exc
    if not stat.S_ISDIR(root_info.st_mode):
        raise QichError("akar paket harus berupa direktori nyata", "SecurityError", "P0152")

    h = hashlib.sha256()
    for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
        kept_dirs = []
        for name in dirs:
            if name in SKIP:
                continue
            path = os.path.join(base, name)
            try:
                info = os.lstat(path)
            except OSError as exc:
                raise QichError("direktori paket berubah saat diperiksa", "SecurityError", "P0152") from exc
            if not stat.S_ISDIR(info.st_mode):
                rel = os.path.relpath(path, root).replace(os.sep, "/")
                raise QichError(
                    f"symlink atau tipe direktori khusus tidak diizinkan dalam paket: {rel}",
                    "SecurityError",
                    "P0152",
                )
            kept_dirs.append(name)
        dirs[:] = sorted(kept_dirs)

        for fn in sorted(files):
            if fn in SKIP or fn.endswith(".pyc"):
                continue
            path = os.path.join(base, fn)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            try:
                info = os.lstat(path)
            except OSError as exc:
                raise QichError("file paket berubah saat diperiksa", "SecurityError", "P0152") from exc
            if not stat.S_ISREG(info.st_mode):
                raise QichError(
                    f"symlink atau file khusus tidak diizinkan dalam paket: {rel}",
                    "SecurityError",
                    "P0152",
                )

            flags = (
                os.O_RDONLY
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
            )
            try:
                fd = os.open(path, flags)
            except OSError as exc:
                raise QichError("file paket tidak dapat dibuka dengan aman", "SecurityError", "P0152") from exc

            try:
                opened = os.fstat(fd)
                if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(info, opened):
                    raise QichError(
                        f"file paket berubah atau bukan file reguler: {rel}",
                        "SecurityError",
                        "P0152",
                    )
                with os.fdopen(fd, "rb") as stream:
                    fd = None
                    file_hash = hashlib.sha256()
                    while True:
                        chunk = stream.read(64 * 1024)
                        if not chunk:
                            break
                        file_hash.update(chunk)
                h.update(rel.encode("utf-8") + b"\\0" + file_hash.digest())
            finally:
                if fd is not None:
                    os.close(fd)
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
        out.append("\\n[[package]]")
        for k in ("name", "version", "source", "sha256", "archive_sha256"):
            if k in e: out.append(f'{k} = "{e[k]}"')
    with open(os.path.join(root, "qh.lock"), "w", encoding="utf-8") as f: f.write("\\n".join(out) + "\\n")
