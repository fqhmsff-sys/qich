"""Registry lokal berbasis direktori (index.json + arsip .qhpkg). Registry HTTPS: PLANNED."""
import errno
import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from ..compiler.diagnostics import QichError
from .manifest import RESERVED, NAME_RE
from .lock import SKIP, MAX_VERSION_COMPONENT_DIGITS

MAX_INDEX_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_PACKAGE_CONTENT_BYTES = 100 * 1024 * 1024


def _vt(v): return tuple(int(x) for x in v.split("."))


def _norm(name):
    n = name.lower().replace("-", "").replace("_", "").replace(".", "")
    for a, b in (("0", "o"), ("1", "l"), ("rn", "m"), ("vv", "w")): n = n.replace(a, b)
    return n


def _dist(a, b):  # Damerau-Levenshtein (OSA)
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1): d[i][0] = i
    for j in range(len(b) + 1): d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            c = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + c)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


def similar_names(name, names):
    out = []
    for n in names:
        if n == name: continue
        if _norm(n) == _norm(name) or (len(name) >= 4 and _dist(name, n) <= 1): out.append(n)
    return out


def index_path(reg): return os.path.join(reg, "index.json")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("kunci JSON registry duplikat")
        result[key] = value
    return result


def _reject_json_constant(value):
    raise ValueError("konstanta JSON non-finite tidak diizinkan: " + value)


def _read_bounded_regular(path, limit, label, missing_code, error_code):
    """Read a bounded regular file without following a leaf symlink."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | nofollow
    try:
        fd = os.open(path, flags)
    except FileNotFoundError as exc:
        raise QichError(f"{label} tidak ditemukan", "RegistryError", missing_code) from exc
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise QichError(f"{label} tidak boleh berupa symlink", "SecurityError", error_code) from exc
        raise QichError(f"{label} tidak dapat dibaca", "RegistryError", error_code) from exc

    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise QichError(f"{label} harus berupa file reguler", "SecurityError", error_code)
        if not nofollow:
            try:
                current = os.lstat(path)
            except OSError as exc:
                raise QichError(f"{label} berubah saat dibuka", "SecurityError", error_code) from exc
            if stat.S_ISLNK(current.st_mode) or not os.path.samestat(current, opened):
                raise QichError(f"{label} tidak boleh berupa symlink atau berubah saat dibuka", "SecurityError", error_code)

        stream = os.fdopen(fd, "rb")
        fd = None
        with stream:
            raw = stream.read(limit + 1)
    except QichError:
        raise
    except OSError as exc:
        raise QichError(f"{label} tidak dapat dibaca", "RegistryError", error_code) from exc
    finally:
        if fd is not None:
            os.close(fd)

    if len(raw) > limit:
        raise QichError(f"{label} melampaui batas ukuran", "ResourceLimit", error_code)
    return raw


def _write_index_atomic(reg, idx):
    """Replace index.json atomically; os.replace replaces a symlink itself, not its target."""
    try:
        raw = json.dumps(idx, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise QichError("index registry tidak dapat diserialisasi", "RegistryError", "P0101") from exc
    if len(raw) > MAX_INDEX_BYTES:
        raise QichError("index registry melampaui batas ukuran", "ResourceLimit", "P0101")

    fd, temporary = tempfile.mkstemp(prefix=".qich-index-", dir=reg)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, index_path(reg))
    except OSError as exc:
        raise QichError("index registry tidak dapat ditulis secara atomik", "RegistryError", "P0101") from exc
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class _BoundedWriter:
    """Seekable ZIP output that refuses to grow beyond the configured archive limit."""
    def __init__(self, stream, limit):
        self.stream = stream
        self.limit = limit

    def write(self, data):
        position = self.stream.tell()
        self.stream.seek(0, os.SEEK_END)
        current_size = self.stream.tell()
        self.stream.seek(position, os.SEEK_SET)
        if max(current_size, position + len(data)) > self.limit:
            raise QichError("arsip paket melampaui batas ukuran registry", "ResourceLimit", "P0131")
        return self.stream.write(data)

    def tell(self):
        return self.stream.tell()

    def seek(self, offset, whence=os.SEEK_SET):
        return self.stream.seek(offset, whence)

    def flush(self):
        return self.stream.flush()

    def seekable(self):
        return True


def _publish_walk_error(exc):
    raise QichError(
        "direktori paket tidak dapat dibaca lengkap saat dipublikasikan",
        "SecurityError",
        "P0131",
    ) from exc


def _write_package_archive(pkg_dir, registry_dir, archive_path):
    """Build a bounded ZIP from verified file descriptors, then publish exclusively."""

    try:
        root_info = os.lstat(pkg_dir)
    except OSError as exc:
        raise QichError("direktori paket tidak dapat dibaca", "RegistryError", "P0131") from exc
    if not stat.S_ISDIR(root_info.st_mode):
        raise QichError("direktori paket harus berupa direktori nyata, bukan symlink", "SecurityError", "P0131")
    package_root = os.path.realpath(pkg_dir)

    fd, temporary = tempfile.mkstemp(prefix=".qich-publish-", suffix=".tmp", dir=registry_dir)
    try:
        with os.fdopen(fd, "w+b") as raw:
            writer = _BoundedWriter(raw, MAX_ARCHIVE_BYTES)
            total_uncompressed = 0
            with zipfile.ZipFile(writer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for base, dirs, files in os.walk(package_root, followlinks=False, onerror=_publish_walk_error):
                    dirs[:] = sorted(name for name in dirs if name not in SKIP)
                    for dirname in dirs:
                        path = os.path.join(base, dirname)
                        try:
                            mode = os.lstat(path).st_mode
                        except OSError as exc:
                            raise QichError("direktori paket berubah saat dipublikasikan", "RegistryError", "P0131") from exc
                        if not stat.S_ISDIR(mode):
                            raise QichError("symlink atau tipe direktori khusus tidak diizinkan dalam paket", "SecurityError", "P0131")

                    for filename in sorted(files):
                        if filename in SKIP:
                            continue
                        path = os.path.join(base, filename)
                        try:
                            info = os.lstat(path)
                        except OSError as exc:
                            raise QichError("file paket berubah saat dipublikasikan", "RegistryError", "P0131") from exc
                        if not stat.S_ISREG(info.st_mode):
                            raise QichError("symlink atau file khusus tidak diizinkan dalam paket", "SecurityError", "P0131")

                        nofollow = getattr(os, "O_NOFOLLOW", 0)
                        flags = (
                            os.O_RDONLY
                            | getattr(os, "O_BINARY", 0)
                            | nofollow
                            | getattr(os, "O_NONBLOCK", 0)
                        )
                        try:
                            source_fd = os.open(path, flags)
                        except OSError as exc:
                            raise QichError(
                                "file paket berubah atau tidak dapat dibuka tanpa mengikuti symlink",
                                "SecurityError",
                                "P0131",
                            ) from exc

                        try:
                            try:
                                opened = os.fstat(source_fd)
                                if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(info, opened):
                                    raise QichError(
                                        "file paket berubah atau bukan file reguler",
                                        "SecurityError",
                                        "P0131",
                                    )
                                if not nofollow:
                                    current = os.lstat(path)
                                    if stat.S_ISLNK(current.st_mode) or not os.path.samestat(current, opened):
                                        raise QichError(
                                            "file paket berubah menjadi symlink saat dibuka",
                                            "SecurityError",
                                            "P0131",
                                        )
                            except OSError as exc:
                                raise QichError(
                                    "file paket berubah saat dibuka untuk publikasi",
                                    "SecurityError",
                                    "P0131",
                                ) from exc

                            if opened.st_size < 0 or total_uncompressed + opened.st_size > MAX_PACKAGE_CONTENT_BYTES:
                                raise QichError(
                                    "konten paket melampaui batas ekstraksi 100 MiB",
                                    "ResourceLimit",
                                    "P0131",
                                )

                            source_stream = os.fdopen(source_fd, "rb")
                            source_fd = None
                            arcname = os.path.relpath(path, package_root).replace(os.sep, "/")
                            zip_info = zipfile.ZipInfo(arcname)
                            zip_info.compress_type = zipfile.ZIP_DEFLATED
                            zip_info.create_system = 3
                            zip_info.external_attr = (
                                stat.S_IFREG | (opened.st_mode & 0o777)
                            ) << 16
                            file_bytes = 0
                            with source_stream as source:
                                with archive.open(zip_info, "w", force_zip64=True) as target:
                                    while True:
                                        chunk = source.read(64 * 1024)
                                        if not chunk:
                                            break
                                        file_bytes += len(chunk)
                                        if total_uncompressed + file_bytes > MAX_PACKAGE_CONTENT_BYTES:
                                            raise QichError(
                                                "konten paket melampaui batas ekstraksi 100 MiB",
                                                "ResourceLimit",
                                                "P0131",
                                            )
                                        target.write(chunk)
                            total_uncompressed += file_bytes
                        finally:
                            if source_fd is not None:
                                os.close(source_fd)

            raw.flush()
            os.fsync(raw.fileno())
            raw.seek(0)
            digest = hashlib.sha256()
            while True:
                chunk = raw.read(64 * 1024)
                if not chunk:
                    break
                digest.update(chunk)

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        output_fd = os.open(archive_path, flags, 0o600)
        try:
            with os.fdopen(output_fd, "wb") as output, open(temporary, "rb") as source:
                while True:
                    chunk = source.read(64 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        except Exception:
            try:
                os.unlink(archive_path)
            except OSError:
                pass
            raise
        return digest.hexdigest()
    except FileExistsError as exc:
        raise QichError("arsip versi sudah ada dan tidak boleh ditimpa", "RegistryError", "P0130") from exc
    except QichError:
        raise
    except OSError as exc:
        raise QichError("arsip paket tidak dapat dibuat atau dipublikasikan", "RegistryError", "P0131") from exc
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_index(reg):
    raw = _read_bounded_regular(index_path(reg), MAX_INDEX_BYTES, "index registry", "P0100", "P0101")
    try:
        idx = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise QichError("index registry tidak valid", "RegistryError", "P0101") from exc
    if (
        not isinstance(idx, dict)
        or not isinstance(idx.get("packages"), dict)
        or ("advisories" in idx and not isinstance(idx["advisories"], dict))
    ):
        raise QichError("index registry tidak valid", "RegistryError", "P0101")
    return idx


def resolve(reg, name, spec):
    idx = load_index(reg)
    p = idx["packages"].get(name)
    if not isinstance(p, dict) or not isinstance(p.get("versions"), dict) or not p["versions"]:
        raise QichError(f"paket '{name}' tidak ada di registry", "RegistryError", "P0102")

    vs = []
    for version, metadata in p["versions"].items():
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
            continue
        if any(len(part) > MAX_VERSION_COMPONENT_DIGITS for part in version.split(".")):
            continue
        if not isinstance(metadata, dict):
            raise QichError(f"metadata versi '{version}' tidak valid", "RegistryError", "P0101")
        yanked = metadata.get("yanked", False)
        if type(yanked) is not bool:
            raise QichError(f"status yanked versi '{version}' tidak valid", "RegistryError", "P0101")
        if not yanked:
            vs.append(version)

    spec = (spec or "*").strip()
    if spec in ("*", ""):
        cand = vs
    elif spec.startswith("^"):
        raw = spec[1:]
        parts = raw.split(".")
        if not 1 <= len(parts) <= 3 or any(
            not re.fullmatch(r"\d{1,%d}" % MAX_VERSION_COMPONENT_DIGITS, x) for x in parts
        ):
            raise QichError(f"rentang versi tidak valid: '{spec}'", "RegistryError", "P0104")
        parts += ["0"] * (3 - len(parts))
        base = tuple(int(x) for x in parts)
        if base[0] > 0:
            upper = (base[0] + 1, 0, 0)
        elif base[1] > 0:
            upper = (0, base[1] + 1, 0)
        else:
            upper = (0, 0, base[2] + 1)
        cand = [v for v in vs if base <= _vt(v) < upper]
    else:
        cand = [v for v in vs if v == spec]

    if not cand:
        raise QichError(f"tidak ada versi '{name}' yang cocok dengan '{spec}'", "RegistryError", "P0103")
    version = max(cand, key=_vt)
    return version, p["versions"][version]


def fetch(reg, name, version, entry):
    if not isinstance(entry, dict):
        raise QichError(f"metadata arsip {name}-{version} tidak valid", "RegistryError", "P0110")
    filename = entry.get("file")
    digest = entry.get("sha256")
    if (
        not isinstance(filename, str) or not filename or "\x00" in filename or len(filename) > 255
        or filename in (".", "..") or os.path.basename(filename) != filename
        or "/" in filename or "\\" in filename
    ):
        raise QichError("nama file arsip registry tidak aman", "SecurityError", "P0111")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise QichError("checksum arsip registry tidak valid", "RegistryError", "P0110")

    root = os.path.realpath(reg)
    path = os.path.join(root, filename)
    if os.path.dirname(os.path.realpath(path)) != root:
        raise QichError("file arsip registry keluar dari direktori registry", "SecurityError", "P0111")
    data = _read_bounded_regular(path, MAX_ARCHIVE_BYTES, f"arsip {name}-{version}", "P0110", "P0111")
    if hashlib.sha256(data).hexdigest() != digest:
        raise QichError(f"checksum arsip {name}-{version} tidak cocok dengan index registry", "IntegrityError", "P0110")
    return data


def check_add(reg, name, allow_similar=False):
    if name in RESERVED:
        raise QichError(f"'{name}' adalah nama cadangan Qich", "RegistryError", "P0120")
    idx = load_index(reg); names = list(idx["packages"])
    if name not in names:
        sim = similar_names(name, names)
        raise QichError(f"paket '{name}' tidak ada di registry", "RegistryError", "P0102",
                        f"maksud Anda: {', '.join(sim)}?" if sim else None)
    sim = similar_names(name, names + sorted(RESERVED))
    if sim and not allow_similar:
        raise QichError(f"nama '{name}' sangat mirip dengan {', '.join(sim)} (potensi typosquatting)", "SecurityError", "P0121",
                        "periksa ejaan; jika memang benar gunakan --allow-similar")


def publish(pkg_dir, name, version, reg):
    if not NAME_RE.match(name) or name in RESERVED:
        raise QichError(f"nama paket tidak boleh dipublikasikan: {name!r}", "RegistryError", "P0120")
    if (
        not isinstance(version, str)
        or not re.fullmatch(r"\d{1,%d}\.\d{1,%d}\.\d{1,%d}" % (
            MAX_VERSION_COMPONENT_DIGITS,
            MAX_VERSION_COMPONENT_DIGITS,
            MAX_VERSION_COMPONENT_DIGITS,
        ), version)
    ):
        raise QichError("versi paket harus berbentuk MAJOR.MINOR.PATCH dengan komponen terbatas", "RegistryError", "P0120")

    os.makedirs(reg, exist_ok=True)
    reg = os.path.realpath(reg)
    try:
        idx = load_index(reg)
    except QichError as exc:
        if exc.code != "P0100":
            raise
        idx = {"packages": {}, "advisories": {}}

    if not isinstance(idx.get("advisories", {}), dict):
        raise QichError("metadata advisory registry tidak valid", "RegistryError", "P0101")

    if name not in idx["packages"]:
        package = {"versions": {}}
        idx["packages"][name] = package
    else:
        package = idx["packages"][name]
    if not isinstance(package, dict) or not isinstance(package.get("versions"), dict):
        raise QichError(f"metadata paket '{name}' tidak valid", "RegistryError", "P0101")
    versions = package["versions"]
    if version in versions:
        raise QichError(f"{name} {version} sudah ada; versi terpublikasi bersifat immutable", "RegistryError", "P0130")

    others = [n for n in idx["packages"] if n != name]
    if not versions:
        sim = similar_names(name, others)
        if sim: raise QichError(f"nama '{name}' terlalu mirip dengan {', '.join(sim)}", "SecurityError", "P0121")

    fname = f"{name}-{version}.qhpkg"
    archive_path = os.path.join(reg, fname)
    digest = _write_package_archive(pkg_dir, reg, archive_path)
    versions[version] = {"file": fname, "sha256": digest}
    try:
        _write_index_atomic(reg, idx)
    except Exception:
        try:
            os.unlink(archive_path)
        except OSError:
            pass
        raise
    return fname


def advisories(reg, name, version):
    try:
        idx = load_index(reg)
    except QichError as exc:
        if exc.code == "P0100":
            return []
        raise
    entries = idx.get("advisories", {})
    if not isinstance(entries, dict):
        return []
    package_entries = entries.get(name, [])
    if not isinstance(package_entries, list):
        return []
    out = []
    for advisory in package_entries:
        if not isinstance(advisory, dict):
            continue
        affected = advisory.get("affected", [])
        if not isinstance(affected, list):
            continue
        for item in affected:
            if not isinstance(item, str):
                continue
            try:
                if item == version or (item.startswith("<") and _vt(version) < _vt(item[1:])):
                    out.append(advisory)
                    break
            except ValueError:
                continue
    return out
