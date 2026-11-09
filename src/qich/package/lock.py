import hashlib
import os
import stat
import tempfile
import tomllib
from ..compiler.diagnostics import QichError

MAX_LOCK_BYTES = 16 * 1024 * 1024

SKIP = {".qh", "build", ".git", "__pycache__", "qh.lock"}


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
                h.update(rel.encode("utf-8") + b"\0" + file_hash.digest())
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
        packages = data.get("package", [])
        if not isinstance(packages, list):
            raise ValueError("package harus berupa array")
        return {entry["name"]: entry for entry in packages}
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError, ValueError) as exc:
        raise QichError("qh.lock tidak valid", "ManifestError", "P0154") from exc


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

    out = ["# Dihasilkan oleh qh. Jangan ubah manual.", "version = 1"]
    for name in sorted(entries):
        e = entries[name]
        out.append("\n[[package]]")
        for k in ("name", "version", "source", "sha256", "archive_sha256"):
            if k in e:
                out.append(f'{k} = "{e[k]}"')
    content = "\n".join(out) + "\n"
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
