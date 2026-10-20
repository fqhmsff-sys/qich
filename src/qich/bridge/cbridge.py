"""Adapter C/C++ (ABI C): ctypes, hanya primitif & string; tanpa pointer mentah."""
import ctypes
import ctypes.util
from ..compiler.diagnostics import QichError

TYPES = {"i32": (ctypes.c_int, -2**31, 2**31 - 1), "i64": (ctypes.c_longlong, -2**63, 2**63 - 1),
         "u32": (ctypes.c_uint, 0, 2**32 - 1), "u64": (ctypes.c_ulonglong, 0, 2**64 - 1),
         "usize": (ctypes.c_size_t, 0, 2**64 - 1), "f32": (ctypes.c_float, None, None),
         "f64": (ctypes.c_double, None, None), "bool": (ctypes.c_bool, None, None),
         "str": (ctypes.c_char_p, None, None), "void": (None, None, None)}


def _ct(name, what):
    if name not in TYPES:
        raise QichError(f"tipe C '{name}' tidak didukung ({what}); tersedia: {', '.join(TYPES)}", "ForeignError", "R0150")
    return TYPES[name]


class CFunc:
    def __init__(self, f, name, args, ret):
        self.f = f; self.name = name; self.args = args; self.ret = ret

    def __qh_call__(self, args, kwargs):
        if kwargs or len(args) != len(self.args):
            raise QichError(f"{self.name}() butuh {len(self.args)} argumen posisi", "TypeError", "R0218")
        conv = []
        for a, t in zip(args, self.args):
            ct, lo, hi = TYPES[t]
            if t == "str":
                if type(a) is not str: raise QichError(f"{self.name}(): argumen str diperlukan", "TypeError", "R0201")
                conv.append(a.encode("utf-8"))
            elif t == "bool":
                if type(a) is not bool: raise QichError(f"{self.name}(): argumen bool diperlukan", "TypeError", "R0201")
                conv.append(a)
            elif t in ("f32", "f64"):
                if type(a) not in (int, float) or type(a) is bool: raise QichError(f"{self.name}(): argumen angka diperlukan", "TypeError", "R0201")
                conv.append(float(a))
            else:
                if type(a) is not int or not lo <= a <= hi:
                    raise QichError(f"{self.name}(): argumen {t} di luar jangkauan/tipe salah", "TypeError", "R0201")
                conv.append(a)
        r = self.f(*conv)
        if self.ret == "str":
            return r.decode("utf-8", errors="replace") if r is not None else None
        return r

    def __qh_repr__(self): return f"<c fn {self.name}>"


class CLib:
    __qh__ = {"fn", "name"}

    def __init__(self, name, lib):
        self.name = name; self.lib = lib

    def fn(self, name, argtypes, restype="void"):
        if type(name) is not str or type(argtypes) is not list:
            raise QichError("fn(nama, [tipe...], tipe_kembali)", "TypeError", "R0201")
        for t in argtypes: _ct(t, "argumen")
        _ct(restype, "kembalian")
        try:
            f = getattr(self.lib, name)
        except AttributeError:
            raise QichError(f"simbol '{name}' tidak ada di library {self.name}", "ForeignError", "R0151")
        f.argtypes = [TYPES[t][0] for t in argtypes]
        f.restype = TYPES[restype][0]
        return CFunc(f, name, list(argtypes), restype)


class CLoader:
    """use c:ffi -> ffi.open(path) untuk library kustom (butuh izin kebijakan)."""
    __qh__ = {"open"}

    def __init__(self, I): self.I = I

    def open(self, path):
        if not (self.I.policy.allow_all or "c:ffi" in self.I.policy.allow):
            raise QichError("membuka library dari path diblokir", "SecurityError", "R0132",
                            'izinkan di qh.toml: [bridge] allow = ["c:ffi"]')
        try:
            return CLib(path, ctypes.CDLL(path))
        except OSError as e:
            raise QichError(f"gagal memuat library: {e}", "ForeignError", "R0152")


def load_c(lib, I):
    if lib == "ffi":
        return CLoader(I)
    name = ctypes.util.find_library(lib)
    if not name:
        raise QichError(f"library C '{lib}' tidak ditemukan", "ImportError", "R0153", "gunakan 'use c:ffi' dengan path jika library kustom")
    try:
        return CLib(name, ctypes.CDLL(name))
    except OSError as e:
        raise QichError(f"gagal memuat '{name}': {e}", "ForeignError", "R0152")
