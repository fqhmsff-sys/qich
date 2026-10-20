"""chyb: HTTP server & client dengan default aman.

Default aman: bind 127.0.0.1, batas body 1MB, timeout socket, header keamanan, error 500 tanpa detail,
static file bebas path-traversal, tanpa CORS. WebSocket: PLANNED.
"""
import json
import os
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ..compiler.diagnostics import QichError
from ..runtime.values import (QFn, BoundMethod, EnumValue, RESULT, Instance, Ok, Err, make_error, type_name)
from ..std.core import to_json, MODULES as STD, HttpResponse

SEC_HEADERS = {
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "Cache-Control": "no-store",
    "Cross-Origin-Resource-Policy": "same-origin",
}
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".json": "application/json",
        ".txt": "text/plain; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml"}


class Request:
    __qh__ = {"method", "path", "query", "params", "headers", "body", "json", "text"}

    def __init__(self, method, path, query, headers, body):
        self.method = method; self.path = path; self.query = query; self.headers = headers
        self.body = body; self.params = {}

    def text(self): return self.body.decode("utf-8", errors="replace")

    def json(self):
        try: return Ok(json.loads(self.text()))
        except ValueError as e: return Err(make_error(f"JSON tidak valid: {e}", "ValueError"))

    def __qh_repr__(self): return f"<Request {self.method} {self.path}>"


class Response:
    __qh__ = {"text", "json", "html", "redirect", "status", "header", "code"}

    def __init__(self, code=200, body=b"", ctype="text/plain; charset=utf-8", headers=None):
        self.code = code; self.body = body; self.headers = dict(headers or {}); self.headers["Content-Type"] = ctype

    @staticmethod
    def text(s, code=200): return Response(code, str(s).encode())

    @staticmethod
    def json(v, code=200):
        return Response(code, json.dumps(to_json(v), ensure_ascii=False).encode(), "application/json")

    @staticmethod
    def html(s, code=200):
        r = Response(code, str(s).encode(), "text/html; charset=utf-8")
        r.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        return r

    @staticmethod
    def redirect(url, code=302):
        if not re.match(r"^(/(?!/)|https?://)", str(url)): raise QichError("URL redirect tidak aman", "ValueError", "R0410")
        r = Response(code, b""); r.headers["Location"] = url; return r

    @staticmethod
    def status(code): return Response(code, b"")

    def header(self, k, v):
        if "\n" in str(k) + str(v) or "\r" in str(k) + str(v): raise QichError("header tidak boleh berisi newline", "ValueError", "R0410")
        self.headers[str(k)] = str(v); return self

    def __qh_repr__(self): return f"<Response {self.code}>"


def _normalize(v):
    if isinstance(v, Response): return v
    if v is None: return Response(204, b"")
    if isinstance(v, str): return Response.text(v)
    if isinstance(v, (dict, list)): return Response.json(v)
    if isinstance(v, HttpResponse): return Response(v.status, v.body)
    if isinstance(v, EnumValue) and v.enum is RESULT:
        if v.variant == "Ok": return _normalize(v.vals[0])
        raise QichError("handler mengembalikan Err", "HandlerError", "R0411")
    raise QichError(f"handler mengembalikan tipe tidak didukung: {type_name(v)}", "HandlerError", "R0411")


class Handle:
    __qh__ = {"port", "stop", "host"}

    def __init__(self, srv, thread):
        self.srv = srv; self.thread = thread; self.port = srv.server_address[1]; self.host = srv.server_address[0]

    def stop(self):
        self.srv.shutdown(); self.srv.server_close(); self.thread.join(timeout=5)


class Server:
    __qh__ = {"get", "post", "put", "delete", "route", "use", "static", "start", "listen", "max_body", "host"}

    def __init__(self, max_body=1_048_576, timeout=10, log=False):
        self.routes = []; self.mw = []; self.statics = []
        self.max_body = int(max_body); self.timeout = timeout; self.log = log
        self.I = None  # diisi oleh MODULES loader

    def route(self, method, pattern, handler):
        if not isinstance(pattern, str) or not pattern.startswith("/"): raise QichError("pola route harus diawali '/'", "ValueError", "R0410")
        rx = re.compile("^" + re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", r"(?P<\1>[^/]+)", re.escape(pattern).replace("\\:", ":")) + "$")
        self.routes.append((method.upper(), rx, handler))

    def get(self, p, h): self.route("GET", p, h)
    def post(self, p, h): self.route("POST", p, h)
    def put(self, p, h): self.route("PUT", p, h)
    def delete(self, p, h): self.route("DELETE", p, h)
    def use(self, mw): self.mw.append(mw)

    def static(self, prefix, directory):
        self.statics.append((prefix.rstrip("/") + "/", os.path.realpath(directory)))

    # ---------------------------------------------------------- dispatch
    def _call(self, h, req):
        return _normalize(self.I.call(h, [req]))

    def dispatch(self, req):
        for prefix, root in self.statics:
            if req.method == "GET" and req.path.startswith(prefix):
                return self._serve_static(root, req.path[len(prefix):])
        path_ok = False
        for method, rx, h in self.routes:
            m = rx.match(req.path)
            if m:
                path_ok = True
                if method == req.method:
                    req.params = {k: urllib.parse.unquote(v) for k, v in m.groupdict().items()}
                    return self._chain(h, req)
        if path_ok:
            r = Response(405, b"Method Not Allowed"); r.headers["Allow"] = ", ".join(sorted({mm for mm, rx, _ in self.routes if rx.match(req.path)}))
            return r
        return Response(404, b"Not Found")

    def _chain(self, h, req):
        def run(i, rq):
            if i == len(self.mw): return self._call(h, rq)
            return _normalize(self.I.call(self.mw[i], [rq, lambda r2=None: run(i + 1, r2 if r2 is not None else rq)]))
        return run(0, req)

    def _serve_static(self, root, rel):
        rel = urllib.parse.unquote(rel)
        target = os.path.realpath(os.path.join(root, rel))
        if "\x00" in rel or not (target == root or target.startswith(root + os.sep)):
            return Response(403, b"Forbidden")
        if not os.path.isfile(target): return Response(404, b"Not Found")
        with open(target, "rb") as f: data = f.read(50 * 1024 * 1024)
        return Response(200, data, MIME.get(os.path.splitext(target)[1].lower(), "application/octet-stream"))

    # ---------------------------------------------------------- http
    def _make_handler(self):
        server = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "chyb"; sys_version = ""
            timeout = server.timeout

            def log_message(self, fmt, *a):
                if server.log: super().log_message(fmt, *a)

            def _send(self, resp):
                self.send_response(resp.code)
                hs = dict(SEC_HEADERS); hs.update(resp.headers)
                for k, v in hs.items(): self.send_header(k, v)
                body = b"" if self.command == "HEAD" else resp.body
                self.send_header("Content-Length", str(len(resp.body)))
                self.send_header("Connection", "close")
                self.end_headers()
                if body and resp.code not in (204, 304): self.wfile.write(body)
                self.close_connection = True

            def _handle(self):
                try:
                    u = urllib.parse.urlsplit(self.path)
                    n = int(self.headers.get("Content-Length") or 0)
                    if n < 0 or n > server.max_body:
                        return self._send(Response(413, b"Payload Too Large"))
                    body = self.rfile.read(n) if n else b""
                    q = {k: v[0] if len(v) == 1 else v for k, v in urllib.parse.parse_qs(u.query).items()}
                    req = Request(self.command, urllib.parse.unquote(u.path), q,
                                  {k.lower(): v for k, v in self.headers.items()}, body)
                    self._send(server.dispatch(req))
                except QichError as e:
                    if server.log: print(f"[chyb] {e}", flush=True)
                    self._send(Response(500, b"Internal Server Error"))
                except (ValueError, TypeError):
                    self._send(Response(400, b"Bad Request"))
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass
                except Exception as e:
                    if server.log: print(f"[chyb] error: {type(e).__name__}", flush=True)
                    self._send(Response(500, b"Internal Server Error"))

            do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_PATCH = _handle

        return H

    def start(self, port=0, host="127.0.0.1"):
        if type(port) is not int or not 0 <= port <= 65535: raise QichError("port tidak valid", "ValueError", "R0410")
        srv = ThreadingHTTPServer((host, port), self._make_handler())
        srv.daemon_threads = True
        t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
        return Handle(srv, t)

    def listen(self, port=8080, host="127.0.0.1"):
        h = self.start(port, host)
        print(f"chyb mendengarkan di http://{h.host}:{h.port} (Ctrl+C untuk berhenti)", flush=True)
        try:
            while True: threading.Event().wait(3600)
        except KeyboardInterrupt:
            h.stop()


def _server_module(I):
    def make(*a, **k):
        s = Server(*a, **k); s.I = I; return s
    return {"Server": make, "Response": Response, "Request": Request}


def _client_module(I):
    return STD["http"](I)


MODULES = {"server": _server_module, "client": _client_module}
