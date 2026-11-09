import os
import shutil
import stat
from ..compiler.diagnostics import QichError
from ..security import safe_extract_zip
from . import manifest, lock, registry
from .manifest import NAME_RE, RESERVED


def _existing_real_directory(path, label):
    """Return whether path exists, rejecting symlink and non-directory entries."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise QichError(f"{label} tidak dapat diperiksa", "SecurityError", "P0153") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise QichError(f"{label} harus berupa direktori nyata, bukan symlink atau file lain", "SecurityError", "P0153")
    return True


def _ensure_real_directory(path, label):
    try:
        os.mkdir(path)
    except FileExistsError:
        pass
    except OSError as exc:
        raise QichError(f"{label} tidak dapat dibuat", "SecurityError", "P0153") from exc
    if not _existing_real_directory(path, label):
        raise QichError(f"{label} tidak tersedia", "SecurityError", "P0153")
    return path


def _ensure_vendor_directory(root):
    """Create and validate .qh/deps without following either directory symlink."""
    root = os.path.realpath(os.path.abspath(root))
    if not _existing_real_directory(root, "akar proyek"):
        raise QichError("akar proyek tidak tersedia", "ManifestError", "P0153")
    state_dir = _ensure_real_directory(os.path.join(root, ".qh"), "direktori .qh")
    return _ensure_real_directory(os.path.join(state_dir, "deps"), "direktori vendor .qh/deps")


def _copy(src, dest):
    if _existing_real_directory(dest, "direktori dependensi vendor"):
        shutil.rmtree(dest)
    # Preserve links if the source changes after hashing; pkg_hash(dest) then rejects them.
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*lock.SKIP, "*.pyc"), symlinks=True)

def registry_path(m):
    return os.environ.get("QH_REGISTRY") or (m.get("registry") or {}).get("path")


def ensure_deps(root, update=False, log=None):
    root = os.path.realpath(os.path.abspath(root))
    m = manifest.load(root)
    old = lock.read(root); new = {}; resolved = {}
    reg = registry_path(m)
    vendor = _ensure_vendor_directory(root)

    def visit(name, spec, base_dir, chain):
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise QichError(f"nama dependensi tidak valid: {name!r}", "ManifestError", "P0004")
        if name in RESERVED:
            raise QichError(f"nama dependensi '{name}' dicadangkan Qich", "SecurityError", "P0120")
        if name in chain:
            raise QichError(f"dependensi melingkar: {' -> '.join(chain + [name])}", "ResolveError", "P0140")
        dest = os.path.join(vendor, name)
        dest_exists = _existing_real_directory(dest, f"direktori dependensi '{name}'")
        if isinstance(spec, dict):
            src = os.path.realpath(os.path.join(base_dir, spec["path"]))
            if not os.path.isdir(src):
                raise QichError(f"path dependensi '{name}' tidak ada: {src}", "ResolveError", "P0141")
            source = "path:" + os.path.relpath(src, root).replace(os.sep, "/")
            sha = lock.pkg_hash(src); dm = manifest.load(src); version = dm["package"]["version"]; arch = None
            copy_from = lambda: _copy(src, dest)
        else:
            if not reg:
                raise QichError(f"dependensi registry '{name}' butuh registry", "ResolveError", "P0142",
                                "set QH_REGISTRY=<dir> atau [registry] path di qh.toml")
            source = "registry:" + os.path.basename(os.path.abspath(reg))
            e = old.get(name)
            if e and not update and e["source"] != source:
                raise QichError(f"sumber '{name}' berubah ({e['source']} -> {source}); kemungkinan dependency confusion", "SecurityError", "P0150",
                                hint="jalankan 'qh update' hanya jika perubahan ini disengaja")
            if e and not update:
                version = e["version"]
                ver, ent = registry.resolve(reg, name, version)
            else:
                ver, ent = registry.resolve(reg, name, spec)
            version = ver
            data = registry.fetch(reg, name, version, ent); arch = ent["sha256"]
            tmp = dest + ".tmp"
            if _existing_real_directory(tmp, f"direktori sementara dependensi '{name}'"):
                shutil.rmtree(tmp)
            safe_extract_zip(data, tmp)
            sha = lock.pkg_hash(tmp); dm = manifest.load(tmp)

            def copy_from():
                if _existing_real_directory(dest, f"direktori dependensi '{name}'"):
                    shutil.rmtree(dest)
                os.replace(tmp, dest)

            if dest_exists and lock.pkg_hash(dest) == sha:
                shutil.rmtree(tmp)
                copy_from = lambda: None
            src = tmp
        if name in resolved:
            if resolved[name]["source"] != source or resolved[name]["version"] != version:
                raise QichError(f"konflik versi/sumber untuk '{name}'", "ResolveError", "P0143")
            return
        e = old.get(name)
        if e and not update:
            if e["source"] != source:
                raise QichError(f"sumber '{name}' berubah ({e['source']} -> {source}); kemungkinan dependency confusion", "SecurityError", "P0150",
                                "jalankan 'qh update' hanya jika perubahan ini disengaja")
            if e["sha256"] != sha:
                raise QichError(f"integritas '{name}' gagal: isi paket berbeda dari qh.lock", "IntegrityError", "P0151",
                                "jika perubahan sah, jalankan 'qh update'")
        if not (dest_exists and lock.pkg_hash(dest) == sha):
            copy_from()
        _existing_real_directory(dest, f"direktori dependensi '{name}'")
        if lock.pkg_hash(dest) != sha:
            raise QichError(f"vendor '{name}' tidak konsisten setelah menyalin", "IntegrityError", "P0151")
        ent = {"name": name, "version": version, "source": source, "sha256": sha}
        if arch: ent["archive_sha256"] = arch
        resolved[name] = ent; new[name] = ent
        for dn, ds in dm.get("dependencies", {}).items():
            visit(dn, ds, src if isinstance(spec, dict) else dest, chain + [name])

    for n, s in m["dependencies"].items():
        visit(n, s, root, [])
    # hapus vendor yatim
    for d in os.listdir(vendor):
        if d in new or d == ".gitkeep" or d.endswith(".tmp"):
            continue
        path = os.path.join(vendor, d)
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise QichError("entri vendor berubah saat dibersihkan", "SecurityError", "P0153") from exc
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise QichError("entri vendor yatim harus berupa direktori/file reguler", "SecurityError", "P0153")
        if stat.S_ISDIR(info.st_mode):
            shutil.rmtree(path)
        else:
            os.unlink(path)
    if update or new != old:
        lock.write(root, new)
        if log: log("qh.lock diperbarui")
    deps = {}
    for n, e in new.items():
        dm = manifest.load(os.path.join(vendor, n))
        deps[n] = {"dir": os.path.join(vendor, n), "version": e["version"], "lib": dm["package"].get("lib", "src/lib.qh")}
    return deps
