"""Kebijakan & utilitas keamanan Qich."""
import io
import os
import re
import secrets
import stat
import tempfile
import unicodedata
import zipfile

PY_DENY = {"os", "sys", "subprocess", "ctypes", "shutil", "socket", "importlib", "builtins",
           "pickle", "marshal", "multiprocessing", "signal", "pty", "resource", "gc", "code",
           "codeop", "runpy", "ensurepip", "pip", "posix", "nt", "_thread", "threading"}
JS_DENY = {
    "assert", "async_hooks", "child_process", "cluster", "dgram",
    "diagnostics_channel", "dns", "fs", "http", "http2", "https",
    "inspector", "module", "net", "os", "perf_hooks", "process",
    "readline", "repl", "sqlite", "tls", "trace_events", "tty",
    "v8", "vm", "wasi", "worker_threads",
}
SECRET_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.I)


class Policy:
    """Kebijakan bridge: modul berbahaya diblokir kecuali di-allow via qh.toml [bridge] allow."""

    def __init__(self, allow=(), allow_all=False):
        self.allow = set(allow); self.allow_all = allow_all

    def check_bridge(self, eco, lib):
        if self.allow_all or f"{eco}:{lib}" in self.allow:
            return True
        if eco == "js":
            root = lib.removeprefix("node:").split("/", 1)[0]
            deny = JS_DENY
        elif eco == "py":
            root = lib.split(".", 1)[0]
            deny = PY_DENY
        else:
            root = lib
            deny = set()
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



def _supports_descriptor_extraction():
    required = (os.open, os.mkdir, os.stat, os.unlink)
    return (
        os.name == "posix"
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and all(function in os.supports_dir_fd for function in required)
    )


def _open_directory_at(parent_fd, name, create):
    """Open one child directory without following a symlink or path ancestor."""
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        if not create:
            raise
        try:
            os.mkdir(name, 0o755, dir_fd=parent_fd)
        except FileExistsError:
            pass
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)

    if not stat.S_ISDIR(before.st_mode):
        raise ValueError("komponen tujuan ekstraksi bukan direktori nyata")

    fd = os.open(name, flags, dir_fd=parent_fd)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISDIR(opened.st_mode) or not os.path.samestat(before, opened):
            raise ValueError("direktori tujuan berubah saat dibuka")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_absolute_directory(path):
    """Walk a resolved absolute path one no-follow directory descriptor at a time."""
    path = os.path.realpath(os.path.abspath(path))
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    fd = os.open(os.sep, flags)
    try:
        for component in path.split(os.sep):
            if not component:
                continue
            child_fd = _open_directory_at(fd, component, True)
            os.close(fd)
            fd = child_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_destination_directory(destination):
    destination = os.path.abspath(destination)
    parent = os.path.dirname(destination) or os.sep
    leaf = os.path.basename(destination)
    parent_fd = _open_absolute_directory(parent)
    try:
        if not leaf:
            return os.dup(parent_fd)
        return _open_directory_at(parent_fd, leaf, True)
    finally:
        os.close(parent_fd)


def _extract_zip_descriptor(zf, validated, destination, max_total):
    """Extract relative to pinned directory descriptors on POSIX."""
    root_fd = None
    try:
        root_fd = _open_destination_directory(destination)
        actual_total = 0
        for zi, member, is_dir in validated:
            parts = member.split("/")
            parent_fd = os.dup(root_fd)
            try:
                for component in parts[:-1]:
                    child_fd = _open_directory_at(parent_fd, component, True)
                    os.close(parent_fd)
                    parent_fd = child_fd

                leaf = parts[-1]
                if is_dir:
                    child_fd = _open_directory_at(parent_fd, leaf, True)
                    os.close(child_fd)
                    continue

                temporary = ".qich-extract-" + secrets.token_hex(16) + ".tmp"
                flags = (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0)
                )
                fd = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
                try:
                    with os.fdopen(fd, "wb") as output:
                        with zf.open(zi, "r") as source:
                            while True:
                                chunk = source.read(64 * 1024)
                                if not chunk:
                                    break
                                actual_total += len(chunk)
                                if actual_total > max_total:
                                    raise ValueError("ukuran hasil ekstraksi melampaui batas")
                                output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    # Rename is relative to the already-open parent. Replacing an
                    # ancestor path with a symlink cannot redirect this operation.
                    os.rename(
                        temporary,
                        leaf,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                    )
                finally:
                    try:
                        os.unlink(temporary, dir_fd=parent_fd)
                    except FileNotFoundError:
                        pass
            finally:
                os.close(parent_fd)
    except OSError as exc:
        raise ValueError("ekstraksi ZIP gagal pada direktori yang dipatok dengan descriptor") from exc
    finally:
        if root_fd is not None:
            os.close(root_fd)


def safe_extract_zip(data: bytes, dest: str, max_files=2000, max_total=100 * 1024 * 1024):
    """Ekstraksi ZIP dengan path portable, collision checks, dan I/O berbatas."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = zf.infolist()
        if len(infos) > max_files:
            raise ValueError("arsip berisi terlalu banyak file")

        total = 0
        destination = os.path.abspath(os.fspath(dest))
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

        if _supports_descriptor_extraction():
            _extract_zip_descriptor(zf, validated, destination, max_total)
            return

        # Path-based fallback for platforms without dir_fd/O_NOFOLLOW support.
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
