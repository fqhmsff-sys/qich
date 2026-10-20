"""Analisis semantik: scope, arity, tipe literal, exhaustiveness sederhana."""
import difflib
from functools import lru_cache
from . import ast as A
from .diagnostics import QichError, Warn

BASIC = {"int", "float", "str", "bool", "nil", "list", "map", "any", "num", "fn", "bytes", "Result", "Task"}


class Checker:
    def __init__(self, file="<src>", builtins=(), exports_of=None):
        self.file = file; self.errors = []; self.warns = []
        self.scopes = [{n: ("builtin", None) for n in builtins}]
        self.exports_of = exports_of or (lambda eco, lib: None)
        self.loops = 0; self.fns = []; self.enums = {}; self.tparams = []

    def err(self, n, msg, code, hint=None, length=1):
        self.errors.append(QichError(msg, "SemanticError", code, n.line, n.col, self.file, length, hint))

    def warn(self, n, msg, code, hint=None):
        self.warns.append(Warn(msg, code, n.line, n.col, self.file, 1, hint))

    def declare(self, name, info=("var", None)):
        self.scopes[-1][name] = info

    def find(self, name):
        for s in reversed(self.scopes):
            if name in s: return s[name]
        return None

    def names(self):
        out = set()
        for s in self.scopes: out |= set(s)
        return out

    # --------------------------------------------------------------
    def check(self, prog):
        self.scopes.append({})
        self.hoist(prog.body)
        for s in prog.body: self.stmt(s)
        return self.errors, self.warns

    def hoist(self, body):
        for s in body:
            t = type(s)
            if t is A.Fn: self.declare(s.name, ("fn", self.arity(s), s))
            elif t is A.Strct: self.declare(s.name, ("strct", len(s.fields), s))
            elif t is A.Enm:
                self.declare(s.name, ("enm", None, s)); self.enums[s.name] = s
                for v in s.variants: self.scopes[-1].setdefault(v.name, ("variant", len(v.fields), s))
            elif t is A.Let and len(self.scopes) == 2:
                self.declare(s.name)
            elif t is A.Use: self.use(s)

    def arity(self, f):
        mn = sum(1 for p in f.params if p.default is None)
        return (mn, len(f.params))

    def use(self, n):
        from ..runtime import stdlib
        alias = n.alias or n.lib.split(".")[-1]
        if n.eco in stdlib.ECOS:
            ex = self.exports_of(n.eco, n.lib)
            if ex is None:
                self.err(n, f"modul '{n.eco}:{n.lib}' tidak ada", "E0110",
                         "modul tersedia: " + ", ".join(sorted(stdlib.available(n.eco))))
                return
            self.declare(alias)
            if n.eco != "std":
                for k in ex: self.scopes[-1].setdefault(k, ("var", None))
        else:
            self.declare(alias)

    # --------------------------------------------------------------
    def infer(self, e):
        t = type(e)
        if t is A.Num: return "float" if type(e.value) is float else "int"
        if t is A.Str or t is A.FStr: return "str"
        if t is A.Bool: return "bool"
        if t is A.Nil: return "nil"
        if t is A.ListLit: return "list"
        if t is A.MapLit: return "map"
        if t is A.Unary and e.op == "!": return "bool"
        if t is A.Binary:
            if e.op in ("==", "!=", "<", ">", "<=", ">=", "&&", "||", "in"): return "bool"
            a, b = self.infer(e.left), self.infer(e.right)
            if a == b and a in ("int", "float", "str", "list"): return a if e.op != "/" else ("float" if a in ("int", "float") else None)
            if {a, b} == {"int", "float"}: return "float"
        if t is A.Call and type(e.func) is A.Ident:
            info = self.find(e.func.name)
            if info and info[0] == "fn":
                r = info[2].ret
                if r is not None and not r.args and not r.nullable and r.name in ("int", "float", "str", "bool", "list", "map"):
                    return r.name
        return None

    def compat(self, tag, ann):
        if tag is None or ann is None or ann.nullable and tag == "nil": return True
        if ann.name in self.tparams[-1] if self.tparams else False: return True
        n = ann.name
        if n in ("any",): return True
        if n in ("int", "float", "num"): return tag == "int" or (tag == "float" and n != "int")
        if n in ("str", "bool", "nil", "list", "map"): return tag == n
        return True

    def type_known(self, t):
        if t.name in BASIC or "." in t.name: return True
        if any(t.name in tp for tp in self.tparams): return True
        return self.find(t.name) is not None

    def ann_check(self, ann, n):
        if ann is None: return
        if not self.type_known(ann):
            self.err(ann, f"tipe '{ann.name}' tidak dikenal", "E0202")
        for a in ann.args: self.ann_check(a, n)

    # --------------------------------------------------------------
    def stmt(self, s):
        getattr(self, "s_" + type(s).__name__)(s)

    def block(self, body):
        self.scopes.append({}); self.hoist_local(body)
        for s in body: self.stmt(s)
        self.scopes.pop()

    def hoist_local(self, body):
        for s in body:
            t = type(s)
            if t is A.Fn: self.declare(s.name, ("fn", self.arity(s), s))
            elif t is A.Strct: self.declare(s.name, ("strct", len(s.fields), s))
            elif t is A.Enm:
                self.declare(s.name, ("enm", None, s)); self.enums[s.name] = s
                for v in s.variants: self.scopes[-1].setdefault(v.name, ("variant", len(v.fields), s))

    def s_Use(self, n):
        if len(self.scopes) > 2:
            if n.eco in ("mod", "pkg"):
                self.err(n, "'use mod:/pkg:' harus berada di level atas file", "E0112")
            self.use(n)

    def s_Let(self, n):
        if n.value is not None: self.expr(n.value)
        if n.ann is not None:
            self.ann_check(n.ann, n)
            if n.value is not None and not self.compat(self.infer(n.value), n.ann):
                self.err(n, f"variabel '{n.name}' bertipe {n.ann.name} tetapi diisi {self.infer(n.value)}", "E0201")
        self.declare(n.name)

    def s_Assign(self, n):
        self.expr(n.value)
        t = n.target
        if type(t) is A.Ident:
            if self.find(t.name) is None:
                self.err(t, f"variabel '{t.name}' belum dideklarasi", "E0120", f"gunakan 'let {t.name} = ...'", len(t.name))
        else:
            self.expr(t)

    def s_ExprStmt(self, n): self.expr(n.expr)
    def s_Block(self, n): self.block(n.body)
    def s_Throw(self, n): self.expr(n.value)

    def s_Return(self, n):
        if not self.fns:
            self.err(n, "'rtrn' di luar fungsi", "E0103")
            return
        if n.value is not None:
            self.expr(n.value)
            f = self.fns[-1]
            if f.ret is not None and not self.compat(self.infer(n.value), f.ret):
                self.err(n, f"fungsi {f.name} mengembalikan {self.infer(n.value)} tetapi dideklarasikan -> {f.ret.name}", "E0203")

    def s_Break(self, n):
        if not self.loops: self.err(n, "'brk' di luar loop", "E0104")

    def s_Continue(self, n):
        if not self.loops: self.err(n, "'cnt' di luar loop", "E0104")

    def s_If(self, n):
        self.expr(n.cond); self.block(n.then)
        if n.els is not None: self.block(n.els)

    def s_While(self, n):
        self.expr(n.cond); self.loops += 1; self.block(n.body); self.loops -= 1

    def s_For(self, n):
        self.expr(n.iter); self.loops += 1
        self.scopes.append({v: ("var", None) for v in n.vars}); self.hoist_local(n.body)
        for s in n.body: self.stmt(s)
        self.scopes.pop(); self.loops -= 1

    def s_Try(self, n):
        self.block(n.body)
        self.scopes.append({n.var: ("var", None)} if n.var else {})
        self.hoist_local(n.handler)
        for s in n.handler: self.stmt(s)
        self.scopes.pop()

    def s_Strct(self, n):
        self.tparams.append(set(n.tparams))
        for p in n.fields:
            self.ann_check(p.ann, p)
            if p.default is not None: self.expr(p.default)
        for m in n.methods: self.fn(m)
        self.tparams.pop()

    def s_Enm(self, n):
        for m in n.methods: self.fn(m)

    def s_Fn(self, n): self.fn(n)

    def fn(self, n):
        self.tparams.append(set(n.tparams))
        for p in n.params:
            self.ann_check(p.ann, p)
            if p.default is not None: self.expr(p.default)
        self.ann_check(n.ret, n)
        self.scopes.append({p.name: ("var", None) for p in n.params})
        self.fns.append(n); saved = self.loops; self.loops = 0
        for c in n.req: self.expr(c.expr)
        if n.body is not None:
            self.hoist_local(n.body)
            for s in n.body: self.stmt(s)
        else:
            self.expr(n.expr_body)
        self.scopes[-1]["result"] = ("var", None)
        for c in n.ens: self.expr(c.expr)
        self.loops = saved; self.fns.pop(); self.scopes.pop(); self.tparams.pop()

    # --------------------------------------------------------------
    def expr(self, e):
        if e is None: return
        t = type(e)
        if t is A.Ident:
            if self.find(e.name) is None:
                m = difflib.get_close_matches(e.name, [x for x in self.names() if not x.startswith("__")], 1)
                self.err(e, f"variabel '{e.name}' tidak dikenal", "E0101", f"maksud Anda '{m[0]}'?" if m else None, len(e.name))
        elif t in (A.Num, A.Str, A.Bool, A.Nil): pass
        elif t is A.FStr:
            for p in e.parts:
                if not isinstance(p, str): self.expr(p)
        elif t is A.ListLit:
            for x in e.items: self.expr(x)
        elif t is A.MapLit:
            for en in e.entries: self.expr(en.key); self.expr(en.value)
        elif t is A.Unary: self.expr(e.operand)
        elif t is A.Binary: self.expr(e.left); self.expr(e.right)
        elif t is A.Ternary: self.expr(e.cond); self.expr(e.a); self.expr(e.b)
        elif t is A.Range: self.expr(e.start); self.expr(e.end)
        elif t is A.Index: self.expr(e.obj); self.expr(e.idx)
        elif t is A.Member: self.expr(e.obj)
        elif t is A.TryOp: self.expr(e.expr)
        elif t is A.Await: self.expr(e.expr)
        elif t is A.FnExpr: self.fn(e.fn)
        elif t is A.Call: self.call(e)
        elif t is A.Match: self.match(e)

    def call(self, e):
        self.expr(e.func)
        for a in e.args: self.expr(a)
        for k in e.kwargs: self.expr(k.value)
        if type(e.func) is A.Ident:
            info = self.find(e.func.name)
            if info and info[0] == "fn":
                mn, mx = info[1]; f = info[2]
                if e.kwargs:
                    names = {p.name for p in f.params}
                    for k in e.kwargs:
                        if k.name not in names:
                            self.err(k, f"{f.name}() tidak punya parameter '{k.name}'", "E0105")
                elif not mn <= len(e.args) <= mx:
                    exp = str(mn) if mn == mx else f"{mn}..{mx}"
                    self.err(e, f"{f.name}() butuh {exp} argumen, diberi {len(e.args)}", "E0105", length=len(f.name))
                else:
                    for p, a in zip(f.params, e.args):
                        if p.ann is not None and not self.compat(self.infer(a), p.ann):
                            self.err(a, f"parameter '{p.name}' butuh {p.ann.name}, diberi {self.infer(a)}", "E0204")
            elif info and info[0] == "strct" and len(e.args) > info[1]:
                self.err(e, f"{e.func.name}() hanya punya {info[1]} field", "E0105")

    def match(self, e):
        self.expr(e.subject)
        variants = set(); enum = None; has_default = False
        for arm in e.arms:
            self.scopes.append({}); self.pat(arm.pat)
            if arm.guard is not None: self.expr(arm.guard)
            if arm.is_block:
                self.hoist_local(arm.body)
                for s in arm.body: self.stmt(s)
            else:
                self.expr(arm.body)
            self.scopes.pop()
            p = arm.pat
            if arm.guard is None:
                for q in (p.alts if type(p) is A.POr else [p]):
                    if type(q) in (A.PWild, A.PBind): has_default = True
                    elif type(q) is A.PVariant:
                        nm = q.name.split(".")[-1]; info = self.find(nm)
                        if info and info[0] == "variant": enum = info[2]; variants.add(nm)
        if enum is not None and not has_default:
            missing = [v.name for v in enum.variants if v.name not in variants]
            if missing:
                self.warn(e, f"mtch pada enm {enum.name} tidak lengkap; belum ada: {', '.join(missing)}", "W0301",
                          "tambahkan varian tersebut atau pola '_'")

    def pat(self, p):
        t = type(p)
        if t is A.PBind: self.declare(p.name)
        elif t is A.PVariant:
            for a in p.args: self.pat(a)
        elif t is A.PList:
            for a in p.items: self.pat(a)
            if p.rest not in (None, "_"): self.declare(p.rest)
        elif t is A.POr:
            for a in p.alts: self.pat(a)


@lru_cache(maxsize=1)
def _default_builtins():
    # Membuat Interp memasang semua builtin cukup sekali per proses.
    from ..runtime.interp import Interp
    import io
    return tuple(Interp(out=io.StringIO()).builtins.vars)


def check_program(prog, file="<src>", builtins=None, exports_of=None):
    if builtins is None:
        builtins = _default_builtins()
    if exports_of is None:
        from ..runtime import stdlib
        exports_of = stdlib.exports_of
    return Checker(file, builtins, exports_of).check(prog)
