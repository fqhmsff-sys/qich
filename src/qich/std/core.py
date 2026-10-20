"""Library standar Qich: fs, json, os, math, time, rand, http."""
import os
import sys
import json as _json
import math as _math
import time as _time
import random as _random
import secrets as _secrets
import subprocess
import urllib.request
import urllib.error
import urllib.parse
import ssl
from ..compiler.diagnostics import QichError
from ..runtime.values import (Ok, Err, make_error, Instance, EnumValue, Secret, to_str, RangeVal)
from ..security import SECRET_RE

MAX_READ = 50 * 1024 * 1024
MAX_HTTP = 10 * 1024 * 1024


def _res(f):
    def w(*a, **k):
        try:
            return Ok(f(*a, **k))
        except QichError:
            raise
        except RecursionError:
            return Err(make_error("data terlalu bersarang", "ValueError"))
        except (OSError, ValueError, TypeError, UnicodeError, urllib.error.URLError, ssl.SSLError, subprocess.SubprocessError) as e:
            return Err(make_error(f"{e}", type(e).__name__))
    w.__name__ = f.__name__
    return w


def _need_str(x, what):
    if type(x) is not str:
        raise QichError(f"{what} harus str", "TypeError", "R0201")
    return x


# ---------------------------------------------------------------- fs
def fs(I):
    @_res
    def read(path):
        _need_str(path, "path")
        if os.path.getsize(path) > MAX_READ: raise ValueError("file terlalu besar")
        with open(path, encoding="utf-8") as f: return f.read()

    @_res
    def read_bytes(path):
        if os.path.getsize(path) > MAX_READ: raise ValueError("file terlalu besar")
        with open(path, "rb") as f: return f.read()

    @_res
    def write(path, data):
        _need_str(path, "path")
        mode = "wb" if type(data) is bytes else "w"
        with open(path, mode, **({} if mode == "wb" else {"encoding": "utf-8"})) as f: f.write(data)
        return None

    @_res
    def append(path, data):
        with open(path, "a", encoding="utf-8") as f: f.write(_need_str(data, "data"))
        return None

    @_res
    def listdir(path="."): return sorted(os.listdir(path))

    @_res
    def mkdir(path): os.makedirs(path, exist_ok=True)

    @_res
    def remove(path):
        if os.path.isdir(path): raise ValueError("remove() hanya untuk file; gunakan remove_dir()")
        os.remove(path)

    @_res
    def remove_dir(path): os.rmdir(path)

    return {"read": read, "read_bytes": read_bytes, "write": write, "append": append, "list": listdir,
            "mkdir": mkdir, "remove": remove, "remove_dir": remove_dir,
            "exists": lambda p: os.path.exists(p), "is_dir": lambda p: os.path.isdir(p),
            "is_file": lambda p: os.path.isfile(p),
            "join": lambda *p: os.path.join(*p), "basename": os.path.basename, "dirname": os.path.dirname,
            "ext": lambda p: os.path.splitext(p)[1]}


# ---------------------------------------------------------------- json
def to_json(v, depth=0):
    if depth > 100: raise ValueError("data terlalu bersarang")
    t = type(v)
    if v is None or t in (bool, int, str): return v
    if t is float:
        if v != v or v in (float("inf"), float("-inf")): raise ValueError("nan/inf tidak valid di JSON")
        return v
    if t is list: return [to_json(x, depth + 1) for x in v]
    if t is dict:
        return {str(k) if type(k) is not str else k: to_json(x, depth + 1) for k, x in v.items()}
    if t is Instance: return {k: to_json(x, depth + 1) for k, x in v.d.items()}
    if t is EnumValue: return {"variant": v.variant, "values": [to_json(x, depth + 1) for x in v.vals]}
    if t is Secret: raise ValueError("Secret tidak boleh diserialisasi")
    if t is RangeVal: return list(v)
    raise ValueError(f"tipe {type(v).__name__} tidak bisa dijadikan JSON")


def json(I):
    @_res
    def parse(s):
        if type(s) is bytes: s = s.decode("utf-8")
        _need_str(s, "input")
        if len(s) > MAX_READ: raise ValueError("JSON terlalu besar")
        return _json.loads(s, parse_constant=lambda c: (_ for _ in ()).throw(ValueError("konstanta tidak valid")))

    @_res
    def stringify(v, indent=None):
        return _json.dumps(to_json(v), indent=indent, ensure_ascii=False, allow_nan=False)

    return {"parse": parse, "stringify": stringify}


# ---------------------------------------------------------------- os
def os_(I):
    def env(name, default=None): return os.environ.get(_need_str(name, "nama"), default)

    def secret(name):
        v = os.environ.get(name)
        return Secret(v) if v is not None else None

    def args(): return list(I.argv) if I is not None else []

    @_res
    def run(cmd, timeout=30, input=None):
        if type(cmd) is not list or not cmd or not all(type(c) is str for c in cmd):
            raise TypeError("run() butuh list str non-kosong (tanpa shell)")
        clean = {k: v for k, v in os.environ.items() if not SECRET_RE.search(k)}
        p = subprocess.run(cmd, capture_output=True, timeout=min(float(timeout), 3600), shell=False,
                           input=input.encode() if isinstance(input, str) else None, env=clean)
        return {"code": p.returncode, "out": p.stdout.decode(errors="replace")[:MAX_READ],
                "err": p.stderr.decode(errors="replace")[:MAX_READ]}

    return {"env": env, "secret": secret, "args": args, "cwd": os.getcwd, "run": run,
            "platform": lambda: sys.platform}


# ---------------------------------------------------------------- math
def math(I):
    def wrap(f):
        def g(*a):
            try: return f(*a)
            except (ValueError, OverflowError, ZeroDivisionError) as e:
                raise QichError(f"{f.__name__}: {e}", "ArithmeticError", "R0202")
        g.__name__ = f.__name__
        return g
    d = {n: wrap(getattr(_math, n)) for n in ("sqrt", "sin", "cos", "tan", "atan", "atan2", "exp", "log",
                                              "log2", "log10", "pow", "hypot", "fabs")}
    d.update({"floor": lambda x: int(_math.floor(x)), "ceil": lambda x: int(_math.ceil(x)),
              "pi": _math.pi, "e": _math.e, "inf": _math.inf, "is_nan": lambda x: x != x})
    return d


# ---------------------------------------------------------------- time
def time(I):
    def sleep(s):
        if type(s) not in (int, float) or s < 0 or s > 3600: raise QichError("sleep() butuh 0..3600 detik", "ValueError")
        _time.sleep(s)
    return {"now": _time.time, "monotonic": _time.monotonic, "sleep": sleep}


# ---------------------------------------------------------------- rand
class Rng:
    __qh__ = {"random", "int", "choice", "shuffle"}

    def __init__(self, seed=None): self.r = _random.Random(seed)
    def random(self): return self.r.random()
    def int(self, a, b): return self.r.randint(a, b)
    def choice(self, xs):
        if not xs: raise QichError("choice() pada list kosong", "ValueError")
        return self.r.choice(xs)
    def shuffle(self, xs): self.r.shuffle(xs)


def rand(I):
    g = Rng()
    return {"Rng": Rng, "random": g.random, "int": g.int, "choice": g.choice, "shuffle": g.shuffle,
            "secure_bytes": lambda n: _secrets.token_bytes(min(int(n), 1 << 20))}


# ---------------------------------------------------------------- http client
class HttpResponse:
    __qh__ = {"status", "ok", "body", "headers", "text", "json"}

    def __init__(self, status, body, headers):
        self.status = status; self.body = body; self.headers = headers
        self.ok = 200 <= status < 300

    def text(self): return self.body.decode("utf-8", errors="replace")

    def json(self):
        try: return Ok(_json.loads(self.text()))
        except ValueError as e: return Err(make_error(f"JSON tidak valid: {e}", "ValueError"))

    def __qh_repr__(self): return f"<HttpResponse {self.status}>"


class _NoDowngrade(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.full_url.startswith("https://") and not newurl.startswith("https://"):
            raise urllib.error.URLError("redirect dari https ke http ditolak")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _loopback(host):
    return host in ("localhost", "127.0.0.1", "::1") or (host or "").startswith("127.")


def http_request(method, url, body=None, headers=None, timeout=10, allow_http=False):
    u = urllib.parse.urlparse(_need_str(url, "url"))
    if u.scheme not in ("http", "https"):
        raise ValueError(f"skema URL tidak didukung: {u.scheme!r}")
    if u.scheme == "http" and not _loopback(u.hostname) and not allow_http:
        raise ValueError("HTTP tanpa TLS ditolak (aman secara default); gunakan https:// atau allow_http: true")
    data = None; hdr = dict(headers or {})
    if body is not None:
        if type(body) in (dict, list):
            data = _json.dumps(to_json(body)).encode(); hdr.setdefault("Content-Type", "application/json")
        elif type(body) is bytes: data = body
        else: data = _need_str(body, "body").encode()
    req = urllib.request.Request(url, data=data, method=method, headers=hdr)
    proxy = urllib.request.ProxyHandler({}) if _loopback(u.hostname) else urllib.request.ProxyHandler()
    opener = urllib.request.build_opener(proxy, _NoDowngrade, urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    try:
        r = opener.open(req, timeout=min(float(timeout), 120))
        status, hd = r.status, r
    except urllib.error.HTTPError as e:
        r = e; status = e.code; hd = e
    data = r.read(MAX_HTTP + 1)
    if len(data) > MAX_HTTP: raise ValueError("respons terlalu besar")
    return HttpResponse(status, data, {k.lower(): v for k, v in hd.headers.items()})


def http(I):
    @_res
    def get(url, headers=None, timeout=10, allow_http=False): return http_request("GET", url, None, headers, timeout, allow_http)

    @_res
    def post(url, body=None, headers=None, timeout=10, allow_http=False): return http_request("POST", url, body, headers, timeout, allow_http)

    @_res
    def request(method, url, body=None, headers=None, timeout=10, allow_http=False):
        return http_request(method.upper(), url, body, headers, timeout, allow_http)

    return {"get": get, "post": post, "request": request}


MODULES = {"fs": fs, "json": json, "os": os_, "math": math, "time": time, "rand": rand, "http": http}
