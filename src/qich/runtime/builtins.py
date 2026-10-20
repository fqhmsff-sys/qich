"""Builtin global & metode tipe bawaan."""
import sys
import queue
import threading
from ..compiler.diagnostics import QichError
from .values import (Env, QFn, BoundMethod, StructDef, Instance, EnumDef, EnumValue, EnumCtor, RangeVal,
                     Namespace, Task, Secret, RESULT, Ok, Err, ERROR_DEF, make_error, type_name,
                     to_str, to_repr, q_eq)

MAX_ALLOC = 50_000_000


def E(msg, kind="RuntimeError", code="R0300", hint=None):
    return QichError(msg, kind, code, hint=hint)


class Channel:
    __qh__ = {"send", "recv", "close"}
    _END = object()

    def __init__(self, size=0):
        self.q = queue.Queue(size)

    def send(self, v): self.q.put(v)

    def recv(self, timeout=None):
        try:
            v = self.q.get(timeout=timeout)
        except queue.Empty:
            return None
        if v is Channel._END:
            self.q.put(v); return None
        return v

    def close(self): self.q.put(Channel._END)


def install(I):
    g = I.builtins.vars

    def _print(*a, sep=" ", end="\n"):
        I.out.write(sep.join(to_str(x) for x in a) + end)
        try: I.out.flush()
        except Exception: pass

    def _len(x):
        if type(x) in (str, list, dict, bytes, RangeVal): return len(x)
        if type(x) is Secret: return x.len()
        raise E(f"len() tidak berlaku untuk {type_name(x)}", "TypeError", "R0201")

    def _str(x): return to_str(x)

    def _int(x):
        if type(x) is bool: return int(x)
        if type(x) is int: return x
        if type(x) is float:
            if x != x or x in (float("inf"), float("-inf")): raise E("tidak bisa mengubah nan/inf menjadi int", "ValueError")
            return int(x)
        if type(x) is str:
            try: return int(x.strip().replace("_", ""), 10)
            except ValueError: raise E(f"tidak bisa mengubah {to_repr(x)} menjadi int", "ValueError", "R0240")
        raise E(f"tidak bisa mengubah {type_name(x)} menjadi int", "TypeError", "R0201")

    def _float(x):
        if type(x) in (int, float, bool): return float(x)
        if type(x) is str:
            try: return float(x.strip())
            except ValueError: raise E(f"tidak bisa mengubah {to_repr(x)} menjadi float", "ValueError", "R0240")
        raise E(f"tidak bisa mengubah {type_name(x)} menjadi float", "TypeError", "R0201")

    def _assert(c, msg="assertion gagal"):
        if c is not True:
            raise E(str(msg), "AssertionError", "R0250")

    def _assert_eq(a, b, msg=None):
        if not q_eq(a, b):
            raise E((msg + ": " if msg else "") + f"diharapkan {to_repr(b)}, dapat {to_repr(a)}", "AssertionError", "R0250")

    def _range(a, b=None):
        if b is None: a, b = 0, a
        if type(a) is not int or type(b) is not int: raise E("range butuh int", "TypeError")
        return RangeVal(a, b)

    def _nums(args):
        if len(args) == 1 and type(args[0]) in (list, RangeVal): return list(args[0])
        return list(args)

    def _min(*a):
        xs = _nums(a)
        if not xs: raise E("min() pada koleksi kosong", "ValueError")
        return min(xs)

    def _max(*a):
        xs = _nums(a)
        if not xs: raise E("max() pada koleksi kosong", "ValueError")
        return max(xs)

    def _sum(xs, start=0):
        t = start
        for x in xs: t = t + x
        return t

    def _sorted(xs, key=None, reverse=False):
        xs = list(I.iterate(xs))
        if key is not None: return sorted(xs, key=lambda x: I.call(key, [x]), reverse=reverse)
        return sorted(xs, reverse=reverse)

    def _panic(msg="panic"): raise E(to_str(msg), "Panic", "R0260")
    def _await_all(ts): return [t.join() for t in ts]

    def _exit(code=0): raise SystemExit(code)

    def _input(prompt=""):
        I.out.write(prompt); I.out.flush()
        line = sys.stdin.readline(1_000_000)
        return line.rstrip("\n") if line else None

    def _bytes(x):
        if type(x) is str: return x.encode("utf-8")
        if type(x) is list:
            if not all(type(i) is int and 0 <= i < 256 for i in x): raise E("bytes() butuh int 0..255", "ValueError")
            return bytes(x)
        if type(x) is bytes: return x
        raise E("bytes() butuh str atau list", "TypeError")

    def _round(x, n=0):
        r = round(x, n)
        return int(r) if n == 0 else r

    g.update({
        "print": _print, "len": _len, "str": _str, "int": _int, "float": _float,
        "bool": lambda x: I.need_bool(x), "type": type_name, "repr": to_repr,
        "abs": abs, "min": _min, "max": _max, "sum": _sum, "round": _round, "sorted": _sorted,
        "range": _range, "assert": _assert, "assert_eq": _assert_eq, "panic": _panic,
        "Ok": Ok, "Err": Err, "Error": ERROR_DEF, "Result": RESULT, "chan": Channel,
        "await_all": _await_all, "exit": _exit, "input": _input, "bytes": _bytes,
        "PI": 3.141592653589793,
    })

    # ---------------- methods
    def need(x, t, what):
        if type(x) is not t: raise E(f"{what} butuh {t.__name__}, dapat {type_name(x)}", "TypeError", "R0201")

    def f1(f, *a): return I.call(f, list(a))

    S = {
        "len": len, "upper": str.upper, "lower": str.lower, "trim": str.strip,
        "starts": lambda s, p: s.startswith(p), "ends": lambda s, p: s.endswith(p),
        "contains": lambda s, p: p in s, "find": lambda s, p: s.find(p),
        "replace": lambda s, a, b: s.replace(a, b), "chars": list, "lines": lambda s: s.split("\n"),
        "split": lambda s, sep=None: s.split(sep) if sep != "" else list(s),
        "repeat": lambda s, n: s * n if len(s) * max(n, 0) <= MAX_ALLOC else (_ for _ in ()).throw(E("hasil terlalu besar", "ResourceLimit")),
        "to_bytes": lambda s: s.encode("utf-8"),
        "pad": lambda s, n, ch=" ": s.ljust(n, ch),
    }

    def l_pop(l, i=-1):
        if not l: raise E("pop() pada list kosong", "IndexError", "R0210")
        return l.pop(i)

    def l_sort(l, key=None, reverse=False):
        if key is not None: l.sort(key=lambda x: I.call(key, [x]), reverse=reverse)
        else: l.sort(reverse=reverse)

    def l_reduce(l, f, init=None):
        acc = init
        it = iter(l)
        if init is None:
            try: acc = next(it)
            except StopIteration: raise E("reduce() pada list kosong tanpa nilai awal", "ValueError")
        for x in it: acc = f1(f, acc, x)
        return acc

    def l_find(l, f):
        for x in l:
            if f1(f, x) is True: return x
        return None

    def l_insert(l, i, x): l.insert(i, x)
    def l_push(l, x): l.append(x)
    def l_remove_at(l, i):
        if not -len(l) <= i < len(l): raise E("indeks di luar batas", "IndexError", "R0210")
        return l.pop(i)

    L = {
        "len": len, "push": l_push, "pop": l_pop, "map": lambda l, f: [f1(f, x) for x in l],
        "filter": lambda l, f: [x for x in l if f1(f, x) is True], "reduce": l_reduce,
        "each": lambda l, f: [f1(f, x) for x in l] and None, "sort": l_sort,
        "reversed": lambda l: l[::-1], "contains": lambda l, x: any(q_eq(x, y) for y in l),
        "index_of": lambda l, x: next((i for i, y in enumerate(l) if q_eq(x, y)), -1),
        "first": lambda l: l[0] if l else None, "last": lambda l: l[-1] if l else None,
        "join": lambda l, sep="": sep.join(to_str(x) for x in l),
        "extend": lambda l, o: l.extend(o), "insert": l_insert, "remove_at": l_remove_at,
        "clear": lambda l: l.clear(), "any": lambda l, f: any(f1(f, x) is True for x in l),
        "all": lambda l, f: all(f1(f, x) is True for x in l),
        "enumerate": lambda l: [[i, x] for i, x in enumerate(l)],
        "zip": lambda l, o: [[a, b] for a, b in zip(l, o)], "sum": lambda l: _sum(l),
        "min": lambda l: _min(l), "max": lambda l: _max(l), "copy": lambda l: list(l), "find": l_find,
    }

    def m_get(m, k, d=None): return m.get(k, d)
    def m_remove(m, k):
        if k not in m: raise E(f"kunci {to_repr(k)} tidak ada", "KeyError", "R0211")
        return m.pop(k)

    M = {
        "len": len, "keys": lambda m: list(m.keys()), "values": lambda m: list(m.values()),
        "items": lambda m: [[k, v] for k, v in m.items()], "get": m_get, "has": lambda m, k: k in m,
        "remove": m_remove, "merge": lambda m, o: {**m, **o}, "clear": lambda m: m.clear(),
        "copy": lambda m: dict(m),
    }
    B = {"len": len, "decode": lambda b: b.decode("utf-8", errors="replace"), "hex": lambda b: b.hex(),
         "to_list": list}
    R = {"len": len, "to_list": list, "contains": lambda r, x: type(x) is int and r.start <= x < r.end}
    I.methods = {str: S, list: L, dict: M, bytes: B, RangeVal: R}

    # ---------------- Result methods
    def r_unwrap(r):
        if r.variant == "Ok": return r.vals[0]
        raise E("unwrap() pada Err: " + _errmsg(r.vals[0]), "UnwrapError", "R0270")

    def r_expect(r, msg):
        if r.variant == "Ok": return r.vals[0]
        raise E(f"{msg}: {_errmsg(r.vals[0])}", "UnwrapError", "R0270")

    def _errmsg(e):
        return e.d["msg"] if type(e) is Instance and "msg" in e.d else to_str(e)

    RESULT.natives.update({
        "is_ok": lambda r: r.variant == "Ok", "is_err": lambda r: r.variant == "Err",
        "unwrap": r_unwrap, "expect": r_expect,
        "unwrap_or": lambda r, d: r.vals[0] if r.variant == "Ok" else d,
        "err": lambda r: r.vals[0] if r.variant == "Err" else None,
        "map": lambda r, f: Ok(f1(f, r.vals[0])) if r.variant == "Ok" else r,
    })
