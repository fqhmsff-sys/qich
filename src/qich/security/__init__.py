"""Kebijakan & utilitas keamanan Qich."""
import io
import os
import re
import zipfile

PY_DENY = {"os", "sys", "subprocess", "ctypes", "shutil", "socket", "importlib", "builtins",
           "pickle", "marshal", "multiprocessing", "signal", "pty", "resource", "gc", "code",
           "codeop", "runpy", "ensurepip", "pip", "posix", "nt", "_thread", "threading"}
JS_DENY = {"child_process", "cluster", "vm", "worker_threads", "inspector", "repl"}
SECRET_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.I)


class Policy:
    """Kebijakan bridge: modul berbahaya diblokir kecuali di-allow via qh.toml [bridge] allow."""

    def __init__(self, allow=(), allow_all=False):
        self.allow = set(allow); self.allow_all = allow_all

    def check_bridge(self, eco, lib):
        if self.allow_all or f"{eco}:{lib}" in self.allow:
            return True
        root = lib.split(".")[0].replace("node:", "")
        deny = PY_DENY if eco == "py" else JS_DENY if eco == "js" else set()
        if root in deny:
            return False
        return True


def safe_extract_zip(data: bytes, dest: str, max_files=2000, max_total=100 * 1024 * 1024):
    """Ekstraksi zip aman: tolak path absolut, '..', symlink, zip-bomb."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    infos = zf.infolist()
    if len(infos) > max_files:
        raise ValueError("arsip berisi terlalu banyak file")
    total = 0
    base = os.path.realpath(dest)
    for zi in infos:
        name = zi.filename
        if name.startswith("/") or ".." in name.replace("\\", "/").split("/") or ":" in name.split("/")[0]:
            raise ValueError(f"path berbahaya di arsip: {name!r}")
        if (zi.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError(f"symlink tidak diizinkan di arsip: {name!r}")
        total += zi.file_size
        if total > max_total:
            raise ValueError("arsip terlalu besar setelah diekstrak")
        target = os.path.realpath(os.path.join(base, name))
        if not (target == base or target.startswith(base + os.sep)):
            raise ValueError(f"path keluar dari tujuan: {name!r}")
    os.makedirs(base, exist_ok=True)
    for zi in infos:
        target = os.path.join(base, zi.filename)
        # Re-check during extraction: an existing symlink inside dest could
        # redirect writes outside the destination after the initial validation.
        resolved = os.path.realpath(target)
        if not (resolved == base or resolved.startswith(base + os.sep)):
            raise ValueError(f"path keluar dari tujuan: {zi.filename!r}")
        if zi.is_dir():
            os.makedirs(target, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            # Parent directories may themselves be symlinks.
            resolved = os.path.realpath(target)
            if not (resolved == base or resolved.startswith(base + os.sep)):
                raise ValueError(f"path keluar dari tujuan: {zi.filename!r}")
            with open(target, "wb") as f:
                f.write(zf.read(zi))
