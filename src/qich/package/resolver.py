import os
import shutil
from ..compiler.diagnostics import QichError
from ..security import safe_extract_zip
from . import manifest, lock, registry
from .manifest import NAME_RE, RESERVED


def _copy(src, dest):
    if os.path.isdir(dest): shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*lock.SKIP, "*.pyc"), symlinks=False)


def registry_path(m):
    return os.environ.get("QH_REGISTRY") or (m.get("registry") or {}).get("path")


def ensure_deps(root, update=False, log=None):
    m = manifest.load(root)
    old = lock.read(root); new = {}; resolved = {}
    reg = registry_path(m)
    vendor = os.path.join(root, ".qh", "deps")
    os.makedirs(vendor, exist_ok=True)

    def visit(name, spec, base_dir, chain):
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise QichError(f"nama dependensi tidak valid: {name!r}", "ManifestError", "P0004")
        if name in RESERVED:
            raise QichError(f"nama dependensi '{name}' dicadangkan Qich", "SecurityError", "P0120")
        if name in chain:
            raise QichError(f"dependensi melingkar: {' -> '.join(chain + [name])}", "ResolveError", "P0140")
        dest = os.path.join(vendor, name)
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
            if os.path.isdir(tmp): shutil.rmtree(tmp)
            safe_extract_zip(data, tmp)
            sha = lock.pkg_hash(tmp); dm = manifest.load(tmp)
            copy_from = lambda: (shutil.rmtree(dest) if os.path.isdir(dest) else None, os.replace(tmp, dest))
            if os.path.isdir(dest) and lock.pkg_hash(dest) == sha:
                shutil.rmtree(tmp); copy_from = lambda: None
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
        if not (os.path.isdir(dest) and lock.pkg_hash(dest) == sha):
            copy_from()
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
        if d not in new and not d.endswith(".tmp"): shutil.rmtree(os.path.join(vendor, d), ignore_errors=True)
    if update or new != old:
        lock.write(root, new)
        if log: log("qh.lock diperbarui")
    deps = {}
    for n, e in new.items():
        dm = manifest.load(os.path.join(vendor, n))
        deps[n] = {"dir": os.path.join(vendor, n), "version": e["version"], "lib": dm["package"].get("lib", "src/lib.qh")}
    return deps
