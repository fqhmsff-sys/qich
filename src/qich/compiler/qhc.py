"""Artifact .qhc: bundle IR terverifikasi (AST ter-serialisasi + checksum SHA-256).

Catatan jujur: checksum mendeteksi korupsi/perubahan tidak disengaja. Keaslian (signature) belum ada (PLANNED).
Loader selalu memverifikasi struktur node (whitelist) sebelum menjalankan apa pun.
"""
import json
import hashlib
from . import ast as A

MAGIC = b"QHC1\n"
MAX_QHC = 64 * 1024 * 1024


def dump(modules, entry, meta=None):
    """modules: {key: {"file": str, "pkg": str|None, "program": Program}}"""
    payload = {"version": 1, "entry": entry, "meta": meta or {},
               "modules": {k: {"file": m["file"], "pkg": m.get("pkg"), "ast": A.to_dict(m["program"])}
                           for k, m in modules.items()}}
    body = json.dumps(payload, separators=(",", ":"), allow_nan=False, sort_keys=True).encode()
    return MAGIC + hashlib.sha256(body).hexdigest().encode() + b"\n" + body


def load(data):
    if len(data) > MAX_QHC:
        raise ValueError("file .qhc terlalu besar")
    if not data.startswith(MAGIC):
        raise ValueError("bukan file .qhc (magic salah)")
    rest = data[len(MAGIC):]
    nl = rest.find(b"\n")
    if nl != 64:
        raise ValueError("header .qhc rusak")
    digest, body = rest[:64].decode("ascii", "replace"), rest[65:]
    if hashlib.sha256(body).hexdigest() != digest:
        raise ValueError("checksum .qhc tidak cocok (file rusak atau dimodifikasi)")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise ValueError(f"isi .qhc bukan JSON valid: {e}")
    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("modules"), dict):
        raise ValueError("struktur .qhc tidak valid / versi tidak didukung")
    mods = {}
    for k, m in payload["modules"].items():
        prog = A.from_dict(m["ast"])
        if not isinstance(prog, A.Program):
            raise ValueError("modul bukan Program")
        mods[k] = {"file": str(m["file"]), "pkg": m.get("pkg"), "program": prog}
    if payload["entry"] not in mods:
        raise ValueError("entry tidak ada di bundle")
    return mods, payload["entry"], payload.get("meta", {})
