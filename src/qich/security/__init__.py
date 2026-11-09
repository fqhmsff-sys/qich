"""Kebijakan & utilitas keamanan Qich."""
import io
import os
import re
import stat
import tempfile
import unicodedata
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


def _zip_member_path(name):
    """Return a portable canonical path and directory flag for one ZIP member."""
    if not isinstance(name, str) or not name or "\x00" in name:
        raise ValueError("nama file arsip kosong atau tidak valid")
    normalized = unicodedata.normalize("NFC", name.replace("\\", "/"))
    is_dir = normalized.endswith("/")
    if is_dir:
        normalized = normalized[:-1]
    if not normalized or normalized.startswith("/"):
        raise ValueError(f"path absolut/kosong di arsip: {name!r}")

    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"segmen path berbahaya di arsip: {name!r}")

    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update(f"COM{i}" for i in range(1, 10))
    reserved.update(f"LPT{i}" for i in range(1, 10))
    # Windows also reserves the superscript 1/2/3 device-name spellings.
    reserved.update(f"COM{x}" for x in ("¹", "²", "³"))
    reserved.update(f"LPT{x}" for x in ("¹", "²", "³"))
    for part in parts:
        # Colon also rejects NTFS alternate data streams and drive-like segments.
        if ":" in part or part != part.rstrip(" ."):
            raise ValueError(f"komponen path tidak portabel: {name!r}")
        stem = part.split(".", 1)[0].rstrip(" .").upper()
        if stem in reserved:
            raise ValueError(f"nama perangkat Windows tidak diizinkan: {name!r}")

    return "/".join(parts), is_dir


def _within_directory(base, path):
    """Case-normalized containment check that also handles filesystem roots."""
    base_path = os.path.normcase(os.path.realpath(base))
    target_path = os.path.normcase(os.path.realpath(path))
    try:
        return os.path.commonpath((base_path, target_path)) == base_path
    except ValueError:
        # Different Windows drives cannot share a destination root.
        return False


def safe_extract_zip(data: bytes, dest: str, max_files=2000, max_total=100 * 1024 * 1024):
    """Ekstraksi ZIP dengan path portable, collision checks, dan I/O berbatas."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = zf.infolist()
        if len(infos) > max_files:
            raise ValueError("arsip berisi terlalu banyak file")

        total = 0
        destination = os.path.abspath(os.fspath(dest))
        try:
            destination_info = os.lstat(destination)
        except FileNotFoundError:
            os.makedirs(destination, exist_ok=True)
            destination_info = os.lstat(destination)
        except OSError as exc:
            raise ValueError("direktori tujuan ekstraksi tidak dapat diperiksa") from exc
        if not stat.S_ISDIR(destination_info.st_mode):
            raise ValueError("tujuan ekstraksi harus berupa direktori nyata, bukan symlink atau file")
        base = os.path.realpath(destination)
        validated = []
        seen = {}

        for zi in infos:
            member, is_dir = _zip_member_path(zi.filename)
            key = member.casefold()
            if key in seen:
                raise ValueError(f"path duplikat/tidak portabel di arsip: {zi.filename!r}")

            parts = member.split("/")
            for index in range(1, len(parts)):
                parent = "/".join(parts[:index]).casefold()
                if parent in seen and not seen[parent]:
                    raise ValueError(f"file dipakai sebagai direktori di arsip: {zi.filename!r}")
            if not is_dir and any(existing.startswith(key + "/") for existing in seen):
                raise ValueError(f"direktori dipakai sebagai file di arsip: {zi.filename!r}")

            mode = (zi.external_attr >> 16) & 0xFFFF
            kind = stat.S_IFMT(mode)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError(f"tipe file khusus tidak diizinkan di arsip: {zi.filename!r}")
            if kind == stat.S_IFDIR and not is_dir:
                raise ValueError(f"metadata direktori ZIP tidak konsisten: {zi.filename!r}")
            if kind == stat.S_IFREG and is_dir:
                raise ValueError(f"metadata file ZIP tidak konsisten: {zi.filename!r}")

            total += zi.file_size
            if total > max_total:
                raise ValueError("arsip terlalu besar setelah diekstrak")
            seen[key] = is_dir
            validated.append((zi, member, is_dir))

        actual_total = 0
        for zi, member, is_dir in validated:
            target = os.path.join(base, *member.split("/"))
            if not _within_directory(base, target):
                raise ValueError(f"path keluar dari tujuan: {zi.filename!r}")

            if is_dir:
                os.makedirs(target, exist_ok=True)
                if not _within_directory(base, target):
                    raise ValueError(f"path direktori keluar dari tujuan: {zi.filename!r}")
                continue

            parent = os.path.dirname(target)
            os.makedirs(parent, exist_ok=True)
            if not _within_directory(base, target):
                raise ValueError(f"path keluar dari tujuan: {zi.filename!r}")

            fd, temporary = tempfile.mkstemp(prefix=".qich-extract-", dir=parent)
            try:
                with os.fdopen(fd, "wb") as output, zf.open(zi, "r") as source:
                    while True:
                        chunk = source.read(64 * 1024)
                        if not chunk:
                            break
                        actual_total += len(chunk)
                        if actual_total > max_total:
                            raise ValueError("ukuran hasil ekstraksi melampaui batas")
                        output.write(chunk)

                # Re-check immediately before replacing the destination entry.
                if not _within_directory(base, target):
                    raise ValueError(f"path keluar dari tujuan: {zi.filename!r}")
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
