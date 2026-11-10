import hashlib
import json
import os
import re
import stat
import tempfile
import tomllib
from ..compiler.diagnostics import QichError
from .manifest import NAME_RE, RESERVED

MAX_LOCK_BYTES = 16 * 1024 * 1024
LOCK_VERSION = 1
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_LOCK_FIELDS = {"name", "version", "source", "sha256", "archive_sha256"}
_REQUIRED_LOCK_FIELDS = {"name", "version", "source", "sha256"}

SKIP = {".qh", "build", ".git", "__pycache__", "qh.lock"}


def _validate_lock_data(data):
    """Validate the versioned lock schema and reject ambiguous duplicate packages."""
    if not isinstance(data, dict) or set(data) - {"version", "package"}:
        raise ValueError("struktur qh.lock tidak dikenal")
    if type(data.get("version")) is not int or data["version"] != LOCK_VERSION:
        raise ValueError("versi format qh.lock tidak didukung")

    packages = data.get("package", [])
    if not isinstance(packages, list):
        raise ValueError("package harus berupa array")

    entries = {}
    for index, entry in enumerate(packages):
        if not isinstance(entry, dict):
            raise ValueError(f"entri package ke-{index + 1} harus berupa tabel")
        if set(entry) - _LOCK_FIELDS:
            raise ValueError(f"field package tidak dikenal pada entri ke-{index + 1}")
        if not _REQUIRED_LOCK_FIELDS.issubset(entry):
            raise ValueError(f"field package wajib tidak lengkap pada entri ke-{index + 1}")

        name = entry["name"]
        version = entry["version"]
        source = entry["source"]
        digest = entry["sha256"]
        if not isinstance(name, str) or not NAME_RE.fullmatch(name) or name in RESERVED:
            raise ValueError(f"nama package tidak valid pada entri ke-{index + 1}")
        if name in entries:
            raise ValueError(f"entri package duplikat di qh.lock: {name}")
        if not isinstance(version, str) or not re.fullmatch(r"\\d+\\.\\d+\\.\\d+", version):
            raise ValueError(f"versi package tidak valid di qh.lock: {name}")
        if not isinstance(source, str) or not source or "\\x00" in source:
            raise ValueError(f"sumber package tidak valid di qh.lock: {name}")
        if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
            raise ValueError(f"SHA-256 package tidak valid di qh.lock: {name}")

        archive_digest = entry.get("archive_sha256")
        if "archive_sha256" in entry and (
            not isinstance(archive_digest, str) or not _DIGEST_RE.fullmatch(archive_digest)
        ):
            raise ValueError(f"SHA-256 arsip package tidak valid di qh.lock: {name}")
        entries[name] = entry
    return entries


def pkg_hash(d):
    """Hash regular package files; reject links and special files before copying."""
    root = os.path.abspath(os.fspath(d))
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
    path = os.path.join(root, "qh.lock")
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise QichError("qh.lock tidak dapat diperiksa", "ManifestError", "P0154") from exc
    if not stat.S_ISREG(info.st_mode):
        raise QichError("qh.lock harus berupa file reguler, bukan symlink atau file khusus", "SecurityError", "P0154")

    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise QichError("qh.lock tidak dapat dibuka dengan aman", "SecurityError", "P0154") from exc

    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(info, opened):
            raise QichError("qh.lock berubah atau bukan file reguler", "SecurityError", "P0154")
        with os.fdopen(fd, "rb") as stream:
            fd = None
            raw = stream.read(MAX_LOCK_BYTES + 1)
    except OSError as exc:
        raise QichError("qh.lock tidak dapat dibaca", "ManifestError", "P0154") from exc
    finally:
        if fd is not None:
            os.close(fd)

    if len(raw) > MAX_LOCK_BYTES:
        raise QichError("qh.lock melampaui batas ukuran", "ResourceLimit", "P0154")
    try:
        data = tomllib.loads(raw.decode("utf-8"))
        return _validate_lock_data(data)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError, ValueError, RecursionError) as exc:
        raise QichError("qh.lock tidak valid", "ManifestError", "P0154") from exc


def _toml_string(value):
    # JSON basic-string escaping is compatible with TOML basic strings.
    return json.dumps(value, ensure_ascii=False)


def write(root, entries):
    root = os.path.realpath(os.path.abspath(root))
    path = os.path.join(root, "qh.lock")
    try:
        root_info = os.lstat(root)
    except OSError as exc:
        raise QichError("direktori proyek tidak dapat diperiksa", "ManifestError", "P0155") from exc
    if not stat.S_ISDIR(root_info.st_mode):
        raise QichError("akar proyek harus berupa direktori nyata", "SecurityError", "P0155")

    try:
        current = os.lstat(path)
    except FileNotFoundError:
        current = None
    except OSError as exc:
        raise QichError("qh.lock tidak dapat diperiksa sebelum ditulis", "ManifestError", "P0155") from exc
    if current is not None and not stat.S_ISREG(current.st_mode):
        raise QichError("qh.lock harus berupa file reguler; symlink tidak akan ditimpa", "SecurityError", "P0155")

    try:
        ordered_entries = [entries[name] for name in sorted(entries)]
        _validate_lock_data({"version": LOCK_VERSION, "package": ordered_entries})
    except (KeyError, TypeError, ValueError) as exc:
        raise QichError("entri qh.lock tidak valid", "ManifestError", "P0155") from exc

    out = ["# Dihasilkan oleh qh. Jangan ubah manual.", f"version = {LOCK_VERSION}"]
    for name in sorted(entries):
        entry = entries[name]
        out.append("\\n[[package]]")
        for key in ("name", "version", "source", "sha256", "archive_sha256"):
            if key in entry:
                out.append(f"{key} = {_toml_string(entry[key])}")
    content = "\\n".join(out) + "\\n"
    if len(content.encode("utf-8")) > MAX_LOCK_BYTES:
        raise QichError("qh.lock melampaui batas ukuran", "ResourceLimit", "P0155")

    fd, temporary = tempfile.mkstemp(prefix=".qich-lock-", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Replacing a path entry does not follow a symlink swapped in after lstat.
        os.replace(temporary, path)
    except OSError as exc:
        raise QichError("qh.lock tidak dapat ditulis secara atomik", "ManifestError", "P0155") from exc
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
