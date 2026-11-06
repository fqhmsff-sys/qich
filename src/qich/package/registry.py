"""Registry lokal berbasis direktori (index.json + arsip .qhpkg). Registry HTTPS: PLANNED."""
import hashlib
import io
import json
import os
import re
import zipfile
from ..compiler.diagnostics import QichError
from .manifest import RESERVED, NAME_RE
from .lock import SKIP

MAX_INDEX_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_VERSION_COMPONENT_DIGITS = 9


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


def load_index(reg):
    try:
        with open(index_path(reg), "rb") as f:
            raw = f.read(MAX_INDEX_BYTES + 1)
    except FileNotFoundError:
        raise QichError(f"registry '{reg}' tidak punya index.json", "RegistryError", "P0100")
    except OSError as exc:
        raise QichError("index registry tidak dapat dibaca", "RegistryError", "P0101") from exc
    if len(raw) > MAX_INDEX_BYTES:
        raise QichError("index registry melampaui batas ukuran", "ResourceLimit", "P0101")
    try:
        idx = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise QichError("index registry tidak valid", "RegistryError", "P0101") from exc
    if not isinstance(idx, dict) or not isinstance(idx.get("packages"), dict):
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
        not isinstance(filename, str) or not filename or len(filename) > 255
        or filename in (".", "..") or os.path.basename(filename) != filename
        or "/" in filename or "\\" in filename
    ):
        raise QichError("nama file arsip registry tidak aman", "SecurityError", "P0111")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise QichError("checksum arsip registry tidak valid", "RegistryError", "P0110")

    root = os.path.realpath(reg)
    path = os.path.join(root, filename)
    if os.path.islink(path) or os.path.dirname(os.path.realpath(path)) != root:
        raise QichError("file arsip registry tidak boleh berupa symlink/keluar dari registry", "SecurityError", "P0111")
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_ARCHIVE_BYTES + 1)
    except OSError as exc:
        raise QichError(f"arsip {name}-{version} tidak dapat dibaca", "RegistryError", "P0110") from exc
    if len(data) > MAX_ARCHIVE_BYTES:
        raise QichError("arsip registry melampaui batas ukuran", "ResourceLimit", "P0111")
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
    os.makedirs(reg, exist_ok=True)
    try: idx = load_index(reg)
    except QichError: idx = {"packages": {}, "advisories": {}}
    ex = idx["packages"].setdefault(name, {"versions": {}})
    if version in ex["versions"]:
        raise QichError(f"{name} {version} sudah ada; versi terpublikasi bersifat immutable", "RegistryError", "P0130")
    others = [n for n in idx["packages"] if n != name]
    if name not in idx["packages"] or not ex["versions"]:
        sim = similar_names(name, others)
        if sim: raise QichError(f"nama '{name}' terlalu mirip dengan {', '.join(sim)}", "SecurityError", "P0121")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(pkg_dir):
            dirs[:] = sorted(x for x in dirs if x not in SKIP)
            for fn in sorted(files):
                p = os.path.join(base, fn)
                if fn in SKIP or os.path.islink(p): continue
                z.write(p, os.path.relpath(p, pkg_dir).replace(os.sep, "/"))
    data = buf.getvalue(); fname = f"{name}-{version}.qhpkg"
    if len(data) > MAX_ARCHIVE_BYTES:
        raise QichError("arsip paket melampaui batas ukuran registry", "ResourceLimit", "P0131")
    with open(os.path.join(reg, fname), "xb") as f: f.write(data)
    ex["versions"][version] = {"file": fname, "sha256": hashlib.sha256(data).hexdigest()}
    with open(index_path(reg), "w", encoding="utf-8") as f: json.dump(idx, f, indent=2, sort_keys=True)
    return fname


def advisories(reg, name, version):
    try: idx = load_index(reg)
    except QichError: return []
    out = []
    for a in idx.get("advisories", {}).get(name, []):
        aff = a.get("affected", [])
        for r in aff:
            if r == version or (r.startswith("<") and _vt(version) < _vt(r[1:])): out.append(a); break
    return out
