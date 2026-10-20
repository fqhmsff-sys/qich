"""Universal Bridge Layer: registry adapter + capability yang bisa dideteksi."""
from ..compiler.diagnostics import QichError

CAPS = ["values", "calls", "methods", "objects", "errors", "async", "callbacks", "ownership",
        "packages", "collections", "strings", "binary"]


def _caps(**kw):
    return {k: kw.get(k, False) for k in CAPS}


ADAPTERS = {
    "py": dict(name="Python", status="TESTED", isolation="in-process (BUKAN sandbox; modul berbahaya diblokir kebijakan)",
               caps=_caps(values=True, calls=True, methods=True, objects=True, errors=True, callbacks=True,
                          packages="via import Python (tanpa auto-install)", collections=True, strings=True, binary=True,
                          ownership="GC Python; objek dibungkus PyRef", **{"async": False})),
    "js": dict(name="JavaScript (Node.js)", status="TESTED", isolation="proses terpisah (node)",
               caps=_caps(values=True, calls=True, methods=True, objects=True, errors=True, collections=True,
                          strings=True, binary="base64", packages="require() dari node_modules/cwd",
                          ownership="handle di proses node", **{"async": "Promise di-await otomatis"}, callbacks=False)),
    "c": dict(name="C (ABI)", status="TESTED", isolation="in-process (ctypes); tanpa pointer mentah",
              caps=_caps(values=True, calls=True, errors="kode kembali", strings=True, packages="library sistem via find_library",
                         ownership="tanpa pointer: hanya primitif & str", **{"async": False})),
    "cpp": dict(name="C++ (extern \"C\")", status="TESTED", isolation="sama dengan c:",
                caps=_caps(values=True, calls=True, strings=True, errors="kode kembali",
                           ownership="hanya extern \"C\"; tanpa template/kelas", **{"async": False})),
}
PLANNED = {"ts": "TypeScript", "java": "Java", "kotlin": "Kotlin", "go": "Go", "rust": "Rust", "dart": "Dart",
           "swift": "Swift", "cs": "C#/.NET", "php": "PHP", "rb": "Ruby", "r": "R", "julia": "Julia", "lua": "Lua",
           "ex": "Elixir", "erl": "Erlang", "scala": "Scala", "clj": "Clojure", "hs": "Haskell", "ocaml": "OCaml",
           "fs": "F#", "zig": "Zig", "fortran": "Fortran", "perl": "Perl", "groovy": "Groovy",
           "objc": "Objective-C", "vb": "Visual Basic/.NET"}
for _k, _n in PLANNED.items():
    ADAPTERS[_k] = dict(name=_n, status="PLANNED", isolation="-", caps=_caps())


def capabilities_table():
    return [(k, a["name"], a["status"], a["caps"]) for k, a in ADAPTERS.items()]


def load_foreign(eco, lib, I):
    a = ADAPTERS.get(eco)
    if a is None:
        raise QichError(f"ekosistem '{eco}' tidak dikenal", "ImportError", "R0130",
                        "adapter: " + ", ".join(sorted(ADAPTERS)) + " (jalankan 'qh bridges')")
    if a["status"] not in ("TESTED", "IMPLEMENTED", "EXPERIMENTAL"):
        raise QichError(f"adapter '{eco}:' ({a['name']}) berstatus {a['status']} dan belum bisa dipakai", "ImportError",
                        "R0131", "lihat 'qh bridges' untuk adapter yang tersedia")
    if not I.policy.check_bridge(eco, lib):
        raise QichError(f"'{eco}:{lib}' diblokir oleh kebijakan keamanan", "SecurityError", "R0132",
                        f'izinkan eksplisit di qh.toml: [bridge] allow = ["{eco}:{lib}"]')
    if eco == "py":
        from .pybridge import load_py
        return load_py(lib, I)
    if eco == "js":
        from .jsbridge import load_js
        return load_js(lib, I)
    from .cbridge import load_c
    return load_c(lib, I)
