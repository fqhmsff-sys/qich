"""Nilai runtime Qich."""
import threading
import math
from ..compiler.diagnostics import QichError


class ReturnSig(BaseException):
    def __init__(self, value=None): self.value = value
class BreakSig(BaseException): pass
class ContinueSig(BaseException): pass


class Env:
    __slots__ = ("vars", "parent")

    def __init__(self, parent=None):
        self.vars = {}; self.parent = parent

    def lookup(self, name):
        e = self
        while e is not None:
            if name in e.vars:
                return e
            e = e.parent
        return None

    def define(self, name, val):
        self.vars[name] = val


class QFn:
    __slots__ = ("node", "env", "name", "module")

    def __init__(self, node, env, name, module=None):
        self.node = node; self.env = env; self.name = name or "<fn>"; self.module = module


class BoundMethod:
    __slots__ = ("fn", "self")

    def __init__(self, fn, self_):
        self.fn = fn; self.self = self_


class StructDef:
    def __init__(self, name, fields, methods, env, tparams):
        self.name = name; self.fields = fields; self.methods = methods; self.env = env; self.tparams = tparams


class Instance:
    __slots__ = ("sd", "d")

    def __init__(self, sd, d):
        self.sd = sd; self.d = d

    def __eq__(self, o):
        return isinstance(o, Instance) and o.sd is self.sd and o.d == self.d

    __hash__ = None


class EnumDef:
    def __init__(self, name, variants, methods=None, natives=None):
        self.name = name; self.variants = variants  # name -> list of field names
        self.methods = methods or {}; self.natives = natives or {}


class EnumValue:
    __slots__ = ("enum", "variant", "vals")

    def __init__(self, enum, variant, vals):
        self.enum = enum; self.variant = variant; self.vals = vals

    def __eq__(self, o):
        return isinstance(o, EnumValue) and o.enum is self.enum and o.variant == self.variant and o.vals == self.vals

    def __hash__(self):
        return hash((self.variant, len(self.vals)))


class EnumCtor:
    def __init__(self, enum, variant):
        self.enum = enum; self.variant = variant


class RangeVal:
    __slots__ = ("start", "end")

    def __init__(self, start, end):
        self.start = start; self.end = end

    def __iter__(self): return iter(range(self.start, self.end))
    def __len__(self): return max(0, self.end - self.start)
    def __eq__(self, o): return isinstance(o, RangeVal) and (o.start, o.end) == (self.start, self.end)
    __hash__ = None


class Namespace:
    def __init__(self, name, d):
        self.name = name; self.d = d


class Secret:
    """Nilai rahasia: tidak pernah tercetak, tidak bisa melintasi bridge."""
    __slots__ = ("_v",)
    __qh__ = {"reveal", "len"}

    def __init__(self, v): self._v = v
    def reveal(self): return self._v
    def len(self): return len(self._v)
    def __repr__(self): return "***"


class Task:
    __qh__ = {"join", "done"}

    def __init__(self, fn):
        self.value = None; self.err = None; self.fn = fn
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self):
        try:
            self.value = self.fn()
        except BaseException as e:  # diteruskan ke await
            self.err = e

    def join(self):
        self._t.join()
        if self.err is not None:
            raise self.err
        return self.value

    def done(self): return not self._t.is_alive()


RESULT = EnumDef("Result", {"Ok": ["value"], "Err": ["error"]})
ERROR_FIELDS = ["msg", "kind"]


def Ok(v): return EnumValue(RESULT, "Ok", [v])
def Err(v): return EnumValue(RESULT, "Err", [v])


def type_name(v):
    if v is None: return "nil"
    t = type(v)
    if t is bool: return "bool"
    if t is int: return "int"
    if t is float: return "float"
    if t is str: return "str"
    if t is list: return "list"
    if t is dict: return "map"
    if t is bytes: return "bytes"
    if t is Instance: return v.sd.name
    if t is EnumValue: return v.enum.name
    if t in (QFn, BoundMethod, EnumCtor): return "fn"
    if t is RangeVal: return "range"
    if t is StructDef: return "strct"
    if t is EnumDef: return "enm"
    if t is Namespace: return "module"
    if t is Task: return "task"
    if t is Secret: return "secret"
    return t.__name__


def _esc(s):
    out = ['"']
    for ch in s:
        if ch == '"': out.append('\\"')
        elif ch == "\\": out.append("\\\\")
        elif ch == "\n": out.append("\\n")
        elif ch == "\t": out.append("\\t")
        elif ch == "\r": out.append("\\r")
        else: out.append(ch)
    out.append('"')
    return "".join(out)


def to_repr(v, depth=0):
    if depth > 24:
        return "..."
    if v is None: return "nil"
    if v is True: return "true"
    if v is False: return "false"
    t = type(v)
    if t is str: return _esc(v)
    if t is float:
        if math.isnan(v): return "nan"
        if math.isinf(v): return "inf" if v > 0 else "-inf"
        return repr(v)
    if t is int: return str(v)
    if t is list: return "[" + ", ".join(to_repr(x, depth + 1) for x in v) + "]"
    if t is dict: return "{" + ", ".join(f"{to_repr(k, depth + 1)}: {to_repr(x, depth + 1)}" for k, x in v.items()) + "}"
    if t is bytes: return "bytes(" + str(len(v)) + ")"
    if t is Instance:
        return v.sd.name + "(" + ", ".join(f"{k}: {to_repr(x, depth + 1)}" for k, x in v.d.items()) + ")"
    if t is EnumValue:
        if not v.vals: return v.variant
        return v.variant + "(" + ", ".join(to_repr(x, depth + 1) for x in v.vals) + ")"
    if t is QFn: return f"<fn {v.name}>"
    if t is BoundMethod: return f"<method {v.fn.name}>"
    if t is RangeVal: return f"{v.start}..{v.end}"
    if t is StructDef: return f"<strct {v.name}>"
    if t is EnumDef: return f"<enm {v.name}>"
    if t is Namespace: return f"<module {v.name}>"
    if t is Secret: return "***"
    if hasattr(v, "__qh_repr__"): return v.__qh_repr__()
    return f"<{type_name(v)}>"


def to_str(v):
    if type(v) is str:
        return v
    return to_repr(v)


def q_eq(a, b):
    ta, tb = type(a), type(b)
    if ta is bool or tb is bool:
        return ta is tb and a == b
    if ta in (int, float) and tb in (int, float):
        return a == b
    if ta is list and tb is list:
        return len(a) == len(b) and all(q_eq(x, y) for x, y in zip(a, b))
    return a == b


def make_error(msg, kind="Error"):
    return Instance(ERROR_DEF, {"msg": msg, "kind": kind})


from ..compiler import ast as _A  # noqa: E402
ERROR_DEF = StructDef("Error", [_A.Param(name="msg", ann=None, default=None),
                                _A.Param(name="kind", ann=None, default=_A.Str(value="Error"))], {}, None, [])
