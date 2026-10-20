"""Adapter Python: in-process, objek dibungkus PyRef."""
import importlib
from ..compiler.diagnostics import QichError
from ..runtime.values import (QFn, BoundMethod, EnumCtor, StructDef, Instance, Secret, RangeVal, Ok, Err)


def ferr(e):
    return QichError(f"{type(e).__name__}: {e}", "ForeignError", "R0140")


def to_q(x, I, depth=0):
    if depth > 50: raise QichError("struktur bridge terlalu dalam", "ForeignError", "R0141")
    if x is None or type(x) in (bool, int, float, str, bytes): return x
    if type(x) in (list, tuple): return [to_q(i, I, depth + 1) for i in x]
    if type(x) in (set, frozenset): return [to_q(i, I, depth + 1) for i in x]
    if type(x) is dict and all(type(k) in (str, int, float, bool) for k in x):
        return {k: to_q(v, I, depth + 1) for k, v in x.items()}
    return PyRef(x, I)


def to_py(x, I, depth=0):
    if depth > 50: raise QichError("struktur bridge terlalu dalam", "ForeignError", "R0141")
    t = type(x)
    if x is None or t in (bool, int, float, str, bytes): return x
    if t is list: return [to_py(i, I, depth + 1) for i in x]
    if t is dict: return {k: to_py(v, I, depth + 1) for k, v in x.items()}
    if t is PyRef: return x.obj
    if t is RangeVal: return list(x)
    if t is Instance: return {k: to_py(v, I, depth + 1) for k, v in x.d.items()}
    if t is Secret: raise QichError("Secret tidak boleh melintasi bridge (gunakan .reveal() secara sadar)", "SecurityError", "R0142")
    if t in (QFn, BoundMethod, EnumCtor, StructDef):
        def cb(*a, **k):
            return to_py(I.call(x, [to_q(i, I) for i in a], {kk: to_q(v, I) for kk, v in k.items()}), I)
        return cb
    return x


class PyRef:
    __slots__ = ("obj", "I")

    def __init__(self, obj, I): self.obj = obj; self.I = I

    def __qh_get__(self, name):
        if name.startswith("_"):
            raise QichError(f"anggota privat '{name}' diblokir", "SecurityError", "R0143")
        try:
            return to_q(getattr(self.obj, name), self.I)
        except AttributeError:
            raise QichError(f"objek Python tidak punya '{name}'", "AttributeError", "R0206")
        except Exception as e:
            raise ferr(e)

    def __qh_call__(self, args, kwargs):
        try:
            return to_q(self.obj(*[to_py(a, self.I) for a in args], **{k: to_py(v, self.I) for k, v in kwargs.items()}), self.I)
        except QichError: raise
        except Exception as e: raise ferr(e)

    def __qh_iter__(self):
        try: return [to_q(i, self.I) for i in iter(self.obj)]
        except Exception as e: raise ferr(e)

    def __qh_index__(self, i):
        try: return to_q(self.obj[to_py(i, self.I)], self.I)
        except Exception as e: raise ferr(e)

    def __qh_repr__(self):
        return f"<py {type(self.obj).__name__}>"

    def __qh_set__(self, name, v):
        if name.startswith("_"): raise QichError("anggota privat diblokir", "SecurityError", "R0143")
        setattr(self.obj, name, to_py(v, self.I))


def load_py(lib, I):
    try:
        m = importlib.import_module(lib)
    except ImportError as e:
        raise QichError(f"modul Python '{lib}' tidak bisa diimpor: {e}", "ImportError", "R0133",
                        "Qich tidak meng-install paket otomatis (keamanan supply-chain); pasang manual dengan pip")
    return PyRef(m, I)
