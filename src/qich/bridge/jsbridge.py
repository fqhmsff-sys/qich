"""Adapter JavaScript: proses node terpisah, protokol JSON-lines."""
import atexit
import base64
import json
import os
import shutil
import subprocess
import threading
from ..compiler.diagnostics import QichError
from ..runtime.values import Secret, RangeVal, Instance

HELPER = os.path.join(os.path.dirname(__file__), "js_helper.js")


def _helper_path():
    """Saat berjalan dari zipapp (.pyz), ekstrak helper ke file sementara."""
    if os.path.isfile(HELPER):
        return HELPER
    import pkgutil, tempfile
    data = pkgutil.get_data(__package__, "js_helper.js")
    fd, path = tempfile.mkstemp(suffix=".js"); os.write(fd, data); os.close(fd)
    atexit.register(lambda: os.path.exists(path) and os.remove(path))
    return path
_proc = None
_lock = threading.Lock()
_next = 0


def _start():
    global _proc
    node = shutil.which("node")
    if not node:
        raise QichError("Node.js tidak ditemukan di PATH; adapter js: butuh 'node'", "ImportError", "R0134")
    _proc = subprocess.Popen([node, _helper_path()], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
    atexit.register(lambda: _proc and _proc.kill())


def rpc(req, timeout=60):
    global _proc, _next
    with _lock:
        if _proc is None or _proc.poll() is not None:
            _start()
        _next += 1; req["rid"] = _next
        timer = threading.Timer(timeout, lambda: _proc.kill()); timer.start()
        try:
            _proc.stdin.write(json.dumps(req) + "\n"); _proc.stdin.flush()
            line = _proc.stdout.readline()
        except (BrokenPipeError, OSError):
            line = ""
        finally:
            timer.cancel()
        if not line:
            raise QichError("proses node berhenti/timeout", "ForeignError", "R0144")
        resp = json.loads(line)
    if not resp.get("ok"):
        raise QichError(resp.get("e", "kesalahan JS"), "ForeignError", "R0145")
    return resp["r"]


def enc(x, depth=0):
    if depth > 50: raise QichError("struktur terlalu dalam", "ForeignError", "R0141")
    t = type(x)
    if x is None: return {"t": "n"}
    if t in (bool, int, str): return {"t": "v", "v": x}
    if t is float:
        if x != x or x in (float("inf"), float("-inf")): raise QichError("nan/inf tidak bisa dikirim ke JS", "ForeignError", "R0141")
        return {"t": "v", "v": x}
    if t is list: return {"t": "a", "v": [enc(i, depth + 1) for i in x]}
    if t is dict: return {"t": "o", "v": {str(k): enc(v, depth + 1) for k, v in x.items()}}
    if t is bytes: return {"t": "b", "v": base64.b64encode(x).decode()}
    if t is JsRef: return {"t": "h", "id": x.id}
    if t is Instance: return {"t": "o", "v": {k: enc(v, depth + 1) for k, v in x.d.items()}}
    if t is RangeVal: return {"t": "a", "v": [enc(i) for i in x]}
    if t is Secret: raise QichError("Secret tidak boleh melintasi bridge", "SecurityError", "R0142")
    raise QichError(f"{t.__name__} tidak didukung adapter js (callback belum didukung)", "ForeignError", "R0146")


def dec(a):
    k = a["t"]
    if k == "n": return None
    if k == "v": return a["v"]
    if k == "f": return float(a["v"].replace("Infinity", "inf"))
    if k == "a": return [dec(i) for i in a["v"]]
    if k == "o": return {kk: dec(v) for kk, v in a["v"].items()}
    if k == "b": return base64.b64decode(a["v"])
    if k == "h": return JsRef(a["id"], a.get("k", "obj"))
    raise QichError("nilai dari JS tidak dikenal", "ForeignError", "R0147")


class JsRef:
    def __init__(self, id, kind="obj"):
        self.id = id; self.kind = kind

    def __qh_get__(self, name):
        if name == "new" and self.kind == "fn":
            return lambda *a: dec(rpc({"op": "new", "id": self.id, "args": [enc(x) for x in a]}))
        if name.startswith("_"):
            raise QichError("anggota privat diblokir", "SecurityError", "R0143")
        return dec(rpc({"op": "get", "id": self.id, "name": name}))

    def __qh_call__(self, args, kwargs):
        if kwargs: raise QichError("argumen bernama tidak didukung adapter js", "ForeignError", "R0146")
        return dec(rpc({"op": "call", "id": self.id, "args": [enc(x) for x in args]}))

    def __qh_repr__(self): return f"<js {self.kind}#{self.id}>"


def load_js(lib, I):
    return dec(rpc({"op": "import", "lib": lib}))
