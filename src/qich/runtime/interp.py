"""Interpreter Qich (runtime referensi)."""
import sys
import threading
import difflib
from ..compiler import ast as A
from ..compiler.diagnostics import QichError
from ..security import Policy
from .values import *  # noqa
from .values import Env, QFn, BoundMethod, StructDef, Instance, EnumDef, EnumValue, EnumCtor, RangeVal, \
    Namespace, Task, Secret, RESULT, Ok, Err, ERROR_DEF, make_error, type_name, to_str, to_repr, q_eq, \
    ReturnSig, BreakSig, ContinueSig

MAX_ALLOC = 50_000_000


class QichThrow(Exception):
    def __init__(self, value): self.value = value


class ModuleCtx:
    def __init__(self, file, pkg=None): self.file = file; self.pkg = pkg


def rt_err(msg, kind="RuntimeError", code="R0001", hint=None):
    return QichError(msg, kind, code, hint=hint)


def arith(op, a, b):
    ta, tb = type(a), type(b)
    num = (ta is int or ta is float) and (tb is int or tb is float)
    if op == "+":
        if num or (ta is str and tb is str) or (ta is list and tb is list) or (ta is bytes and tb is bytes):
            return a + b
        hint = None
        if ta is str or tb is str:
            hint = 'ubah dengan str(x) atau gunakan f"...{x}..."'
        raise rt_err(f"tidak bisa menjumlahkan {type_name(a)} dan {type_name(b)}", "TypeError", "R0201", hint)
    if op == "-" and num: return a - b
    if op == "*":
        if num: return a * b
        for x, y in ((a, b), (b, a)):
            if type(x) in (str, list) and type(y) is int:
                if len(x) * max(y, 0) > MAX_ALLOC:
                    raise rt_err("hasil terlalu besar", "ResourceLimit", "R0900")
                return x * y
    if op == "/" and num:
        if b == 0:
            raise rt_err("pembagian dengan nol", "ArithmeticError", "R0202")
        return a / b
    if op == "%" and num:
        if b == 0:
            raise rt_err("modulo dengan nol", "ArithmeticError", "R0202")
        return a % b
    raise rt_err(f"operator '{op}' tidak berlaku untuk {type_name(a)} dan {type_name(b)}", "TypeError", "R0201")


def compare(op, a, b):
    ta, tb = type(a), type(b)
    if not (((ta is int or ta is float) and (tb is int or tb is float)) or (ta is str and tb is str)):
        raise rt_err(f"tidak bisa membandingkan {type_name(a)} dengan {type_name(b)}", "TypeError", "R0201")
    return a < b if op == "<" else a > b if op == ">" else a <= b if op == "<=" else a >= b


class Interp:
    def __init__(self, out=None, loader=None, max_steps=0, max_depth=500, policy=None, argv=None):
        self.out = out or sys.stdout
        self.loader = loader; self.max_steps = max_steps; self.steps = 0
        self.max_depth = max_depth; self.tl = threading.local()
        self.policy = policy or Policy(); self.argv = list(argv or [])
        self.builtins = Env(None)
        from . import builtins as B
        B.install(self)
        self._ev = {}; self._ex = {}
        for name in dir(self):
            if name.startswith("ev_"): self._ev[A.NODES[name[3:]]] = getattr(self, name)
            elif name.startswith("ex_"): self._ex[A.NODES[name[3:]]] = getattr(self, name)

    # ------------------------------------------------------------ eval
    def ev(self, n, env):
        try:
            return self._ev[type(n)](n, env)
        except QichError as e:
            if e.line is None:
                e.line = n.line; e.col = n.col
            raise
        except RecursionError:
            raise rt_err("stack overflow (rekursi terlalu dalam)", "ResourceLimit", "R0901")
        except KeyError as e:
            if type(n) not in self._ev:
                raise rt_err(f"node tidak bisa dievaluasi: {type(n).__name__}")
            raise

    def ex(self, n, env):
        if self.max_steps:
            self.steps += 1
            if self.steps > self.max_steps:
                raise rt_err("batas langkah eksekusi terlampaui", "ResourceLimit", "R0902")
        try:
            return self._ex[type(n)](n, env)
        except QichError as e:
            if e.line is None:
                e.line = n.line; e.col = n.col
            raise
        except RecursionError:
            raise rt_err("stack overflow (rekursi terlalu dalam)", "ResourceLimit", "R0901")

    def modctx(self, env):
        e = env.lookup("__module__")
        return e.vars["__module__"] if e else None

    def exec_block(self, stmts, env):
        for s in stmts:
            t = type(s)
            if t is A.Fn:
                env.vars[s.name] = QFn(s, env, s.name, self.modctx(env))
            elif t is A.Strct or t is A.Enm:
                self._ex[t](s, env)
        last = None
        for s in stmts:
            t = type(s)
            if t is A.Fn or t is A.Strct or t is A.Enm:
                continue
            last = self.ex(s, env)
        return last

    def run_module(self, program, file, pkg=None, name="main"):
        env = Env(self.builtins)
        env.vars["__module__"] = ModuleCtx(file, pkg)
        try:
            self.exec_block(program.body, env)
        except ReturnSig:
            raise rt_err("'rtrn' atau '?' di luar fungsi", "RuntimeError", "R0105")
        except QichThrow as t:
            raise rt_err("throw tidak tertangkap: " + to_str(t.value if not isinstance(t.value, Instance) else t.value.d.get("msg")), "Uncaught", "R0106")
        except QichError as e:
            if e.file is None: e.file = file
            raise
        return env

    # ------------------------------------------------------------ statements
    def ex_Use(self, n, env):
        eco, lib = n.eco, n.lib
        alias = n.alias or lib.split(".")[-1]
        from . import stdlib
        if eco in stdlib.ECOS:
            exports, inject = stdlib.load(eco, lib, self)
            env.vars[alias] = Namespace(alias, exports)
            if inject:
                for k, v in exports.items():
                    env.vars.setdefault(k, v)
        elif eco in ("mod", "pkg"):
            if self.loader is None:
                raise rt_err(f"tidak ada proyek untuk memuat '{eco}:{lib}'", code="R0110")
            env.vars[alias] = self.loader.import_module(eco, lib, self.modctx(env), self)
        else:
            from ..bridge import load_foreign
            env.vars[alias] = load_foreign(eco, lib, self)

    def ex_Let(self, n, env):
        v = self.ev(n.value, env) if n.value is not None else None
        if n.ann is not None:
            self.check(v, n.ann, env, None, (), f"variabel '{n.name}'")
        env.vars[n.name] = v

    def ex_ExprStmt(self, n, env):
        return self.ev(n.expr, env)

    def ex_Block(self, n, env):
        self.exec_block(n.body, Env(env))

    def ex_Return(self, n, env):
        raise ReturnSig(self.ev(n.value, env) if n.value is not None else None)

    def ex_Break(self, n, env): raise BreakSig()
    def ex_Continue(self, n, env): raise ContinueSig()

    def need_bool(self, v, what="kondisi"):
        if v is not True and v is not False:
            raise rt_err(f"{what} harus bool, dapat {type_name(v)}", "TypeError", "R0203",
                         "gunakan perbandingan eksplisit, mis. x != nil atau len(x) > 0")
        return v

    def ex_If(self, n, env):
        if self.need_bool(self.ev(n.cond, env)):
            self.exec_block(n.then, Env(env))
        elif n.els is not None:
            self.exec_block(n.els, Env(env))

    def ex_While(self, n, env):
        while self.need_bool(self.ev(n.cond, env)):
            if self.max_steps:
                self.steps += 1
                if self.steps > self.max_steps:
                    raise rt_err("batas langkah eksekusi terlampaui", "ResourceLimit", "R0902")
            try:
                self.exec_block(n.body, Env(env))
            except BreakSig:
                break
            except ContinueSig:
                continue

    def iterate(self, v):
        t = type(v)
        if t is list or t is RangeVal: return v
        # Iterasi langsung menghindari salinan O(n) tambahan untuk koleksi besar.
        if t is str or t is dict or t is bytes: return iter(v)
        if hasattr(v, "__qh_iter__"): return v.__qh_iter__()
        raise rt_err(f"{type_name(v)} tidak bisa diiterasi", "TypeError", "R0204")

    def ex_For(self, n, env):
        src = self.ev(n.iter, env)
        if type(src) is dict and len(n.vars) == 2:
            items = src.items()
        else:
            items = self.iterate(src)
        for x in items:
            e = Env(env)
            if len(n.vars) == 1:
                e.vars[n.vars[0]] = x
            else:
                if type(x) not in (list, tuple) or len(x) != len(n.vars):
                    raise rt_err(f"tidak bisa memecah {to_repr(x)} menjadi {len(n.vars)} variabel", "TypeError", "R0205")
                for nm, val in zip(n.vars, x):
                    e.vars[nm] = val
            if self.max_steps:
                self.steps += 1
                if self.steps > self.max_steps:
                    raise rt_err("batas langkah eksekusi terlampaui", "ResourceLimit", "R0902")
            try:
                self.exec_block(n.body, e)
            except BreakSig:
                break
            except ContinueSig:
                continue

    def ex_Fn(self, n, env):
        env.vars[n.name] = QFn(n, env, n.name, self.modctx(env))

    def ex_Strct(self, n, env):
        sd = StructDef(n.name, n.fields, {}, env, n.tparams)
        ctx = self.modctx(env)
        for m in n.methods:
            sd.methods[m.name] = QFn(m, env, f"{n.name}.{m.name}", ctx)
        env.vars[n.name] = sd

    def ex_Enm(self, n, env):
        ed = EnumDef(n.name, {v.name: v.fields for v in n.variants})
        ctx = self.modctx(env)
        for m in n.methods:
            ed.methods[m.name] = QFn(m, env, f"{n.name}.{m.name}", ctx)
        env.vars[n.name] = ed
        for v in n.variants:
            val = EnumValue(ed, v.name, []) if not v.fields else EnumCtor(ed, v.name)
            env.vars.setdefault(v.name, val)

    def ex_Try(self, n, env):
        try:
            self.exec_block(n.body, Env(env))
            return
        except QichError as e:
            if e.kind == "ResourceLimit" and e.code != "R0901":
                raise
            val = make_error(e.msg, e.kind)
        except QichThrow as t:
            val = t.value
        except RecursionError:
            val = make_error("stack overflow", "ResourceLimit")
        e2 = Env(env)
        if n.var:
            e2.vars[n.var] = val
        self.exec_block(n.handler, e2)

    def ex_Throw(self, n, env):
        raise QichThrow(self.ev(n.value, env))

    def ex_Assign(self, n, env):
        tgt = n.target
        val = self.ev(n.value, env)
        t = type(tgt)
        if t is A.Ident:
            e = env.lookup(tgt.name)
            if e is None:
                raise rt_err(f"variabel '{tgt.name}' belum dideklarasi", "NameError", "R0101", f"gunakan 'let {tgt.name} = ...'")
            if n.op != "=":
                val = arith(n.op[0], e.vars[tgt.name], val)
            e.vars[tgt.name] = val
        elif t is A.Index:
            obj = self.ev(tgt.obj, env); idx = self.ev(tgt.idx, env)
            if n.op != "=":
                val = arith(n.op[0], self.get_index(obj, idx), val)
            self.set_index(obj, idx, val)
        else:
            obj = self.ev(tgt.obj, env)
            if type(obj) is Instance:
                if tgt.name not in obj.d:
                    raise rt_err(f"strct {obj.sd.name} tidak punya field '{tgt.name}'", "AttributeError", "R0206")
                if n.op != "=":
                    val = arith(n.op[0], obj.d[tgt.name], val)
                for p in obj.sd.fields:
                    if p.name == tgt.name and p.ann is not None:
                        self.check(val, p.ann, obj.sd.env, None, obj.sd.tparams, f"field '{tgt.name}'")
                obj.d[tgt.name] = val
            elif hasattr(obj, "__qh_set__"):
                obj.__qh_set__(tgt.name, val)
            else:
                raise rt_err(f"tidak bisa mengisi anggota pada {type_name(obj)}", "AttributeError", "R0206")

    # ------------------------------------------------------------ expressions
    def ev_Num(self, n, env): return n.value
    def ev_Str(self, n, env): return n.value
    def ev_Bool(self, n, env): return n.value
    def ev_Nil(self, n, env): return None
    def ev_FnExpr(self, n, env): return QFn(n.fn, env, "<fn>", self.modctx(env))

    def ev_FStr(self, n, env):
        return "".join(p if type(p) is str else to_str(self.ev(p, env)) for p in n.parts)

    def ev_Ident(self, n, env):
        name = n.name
        e = env
        while e is not None:
            v = e.vars
            if name in v:
                return v[name]
            e = e.parent
        names = []
        e = env
        while e is not None:
            names += [k for k in e.vars if not k.startswith("__")]
            e = e.parent
        m = difflib.get_close_matches(name, names, 1)
        raise rt_err(f"variabel '{name}' belum didefinisikan", "NameError", "R0101",
                     f"maksud Anda '{m[0]}'?" if m else None)

    def ev_ListLit(self, n, env): return [self.ev(x, env) for x in n.items]

    def ev_MapLit(self, n, env):
        d = {}
        for en in n.entries:
            k = self.ev(en.key, env)
            if type(k) not in (str, int, float, bool) and k is not None:
                raise rt_err(f"kunci map tidak valid: {type_name(k)}", "TypeError", "R0207")
            d[k] = self.ev(en.value, env)
        return d

    def ev_Unary(self, n, env):
        v = self.ev(n.operand, env)
        if n.op == "!":
            return not self.need_bool(v, "operand '!'")
        if type(v) in (int, float):
            return -v
        raise rt_err(f"tidak bisa menegasikan {type_name(v)}", "TypeError", "R0201")

    def ev_Binary(self, n, env):
        op = n.op
        if op == "&&":
            if not self.need_bool(self.ev(n.left, env), "operand '&&'"): return False
            return self.need_bool(self.ev(n.right, env), "operand '&&'")
        if op == "||":
            if self.need_bool(self.ev(n.left, env), "operand '||'"): return True
            return self.need_bool(self.ev(n.right, env), "operand '||'")
        a = self.ev(n.left, env); b = self.ev(n.right, env)
        try:
            if op == "==": return q_eq(a, b)
            if op == "!=": return not q_eq(a, b)
            if op in ("<", ">", "<=", ">="): return compare(op, a, b)
            if op == "in": return self.contains(b, a)
            return arith(op, a, b)
        except (OverflowError, ValueError) as e:
            raise rt_err(f"kesalahan numerik: {e}", "ArithmeticError", "R0202")

    def contains(self, c, x):
        t = type(c)
        if t is list: return any(q_eq(x, y) for y in c)
        if t is dict: return x in c if type(x) in (str, int, float, bool) or x is None else False
        if t is str:
            if type(x) is not str: raise rt_err("'in' pada str butuh str", "TypeError", "R0201")
            return x in c
        if t is RangeVal: return type(x) is int and c.start <= x < c.end
        raise rt_err(f"'in' tidak berlaku untuk {type_name(c)}", "TypeError", "R0201")

    def ev_Ternary(self, n, env):
        return self.ev(n.a if self.need_bool(self.ev(n.cond, env), "kondisi ternary") else n.b, env)

    def ev_Range(self, n, env):
        a = self.ev(n.start, env); b = self.ev(n.end, env)
        if type(a) is not int or type(b) is not int:
            raise rt_err("range butuh dua int", "TypeError", "R0208")
        return RangeVal(a, b + 1 if n.inclusive else b)

    def ev_Index(self, n, env):
        return self.get_index(self.ev(n.obj, env), self.ev(n.idx, env))

    def get_index(self, o, i):
        t = type(o)
        if t is list or t is str or t is bytes:
            if type(i) is RangeVal:
                s = max(0, min(i.start, len(o))); e = max(s, min(i.end, len(o)))
                return o[s:e]
            if type(i) is not int:
                raise rt_err(f"indeks harus int, dapat {type_name(i)}", "TypeError", "R0209")
            if not -len(o) <= i < len(o):
                raise rt_err(f"indeks {i} di luar batas (panjang {len(o)})", "IndexError", "R0210")
            return o[i]
        if t is dict:
            try:
                return o[i]
            except KeyError:
                raise rt_err(f"kunci {to_repr(i)} tidak ada di map", "KeyError", "R0211", "gunakan m.get(kunci, default)")
            except TypeError:
                raise rt_err(f"kunci tidak valid: {type_name(i)}", "TypeError", "R0207")
        if hasattr(o, "__qh_index__"):
            return o.__qh_index__(i)
        raise rt_err(f"{type_name(o)} tidak bisa diindeks", "TypeError", "R0209")

    def set_index(self, o, i, v):
        t = type(o)
        if t is list:
            if type(i) is not int:
                raise rt_err("indeks harus int", "TypeError", "R0209")
            if not -len(o) <= i < len(o):
                raise rt_err(f"indeks {i} di luar batas (panjang {len(o)})", "IndexError", "R0210")
            o[i] = v
        elif t is dict:
            if type(i) not in (str, int, float, bool) and i is not None:
                raise rt_err(f"kunci map tidak valid: {type_name(i)}", "TypeError", "R0207")
            o[i] = v
        else:
            raise rt_err(f"{type_name(o)} tidak mendukung assignment indeks", "TypeError", "R0209")

    def ev_Member(self, n, env):
        return self.get_member(self.ev(n.obj, env), n.name)

    def get_member(self, o, name):
        t = type(o)
        if t is Instance:
            if name in o.d: return o.d[name]
            m = o.sd.methods.get(name)
            if m is not None: return BoundMethod(m, o)
            cands = list(o.d) + list(o.sd.methods)
            c = difflib.get_close_matches(name, cands, 1)
            raise rt_err(f"{o.sd.name} tidak punya anggota '{name}'", "AttributeError", "R0206", f"maksud Anda '{c[0]}'?" if c else None)
        if t is Namespace:
            if name in o.d: return o.d[name]
            c = difflib.get_close_matches(name, list(o.d), 1)
            raise rt_err(f"modul '{o.name}' tidak punya '{name}'", "AttributeError", "R0206", f"maksud Anda '{c[0]}'?" if c else None)
        if t is StructDef:
            if name in o.methods: return o.methods[name]
            raise rt_err(f"strct {o.name} tidak punya metode '{name}'", "AttributeError", "R0206")
        if t is EnumDef:
            if name in o.variants:
                return EnumValue(o, name, []) if not o.variants[name] else EnumCtor(o, name)
            if name in o.methods: return o.methods[name]
            raise rt_err(f"enm {o.name} tidak punya varian '{name}'", "AttributeError", "R0206")
        if t is EnumValue:
            f = o.enum.natives.get(name)
            if f is not None:
                return lambda *a, **k: f(o, *a, **k)
            m = o.enum.methods.get(name)
            if m is not None: return BoundMethod(m, o)
            raise rt_err(f"{o.enum.name} tidak punya anggota '{name}'", "AttributeError", "R0206")
        tbl = self.methods.get(t)
        if tbl is not None:
            f = tbl.get(name)
            if f is None:
                c = difflib.get_close_matches(name, list(tbl), 1)
                raise rt_err(f"{type_name(o)} tidak punya metode '{name}'", "AttributeError", "R0206", f"maksud Anda '{c[0]}'?" if c else None)
            return lambda *a, **k: f(o, *a, **k)
        if hasattr(o, "__qh_get__"):
            return o.__qh_get__(name)
        q = getattr(o, "__qh__", None)
        if q is not None and name in q:
            return getattr(o, name)
        raise rt_err(f"{type_name(o)} tidak punya anggota '{name}'", "AttributeError", "R0206")

    def ev_TryOp(self, n, env):
        v = self.ev(n.expr, env)
        if type(v) is EnumValue and v.enum is RESULT:
            if v.variant == "Ok":
                return v.vals[0]
            raise ReturnSig(v)
        raise rt_err(f"operator '?' butuh Result, dapat {type_name(v)}", "TypeError", "R0212")

    def ev_Await(self, n, env):
        v = self.ev(n.expr, env)
        if type(v) is Task:
            return v.join()
        raise rt_err(f"'await' butuh task, dapat {type_name(v)}", "TypeError", "R0213", "panggil fungsi 'async fn' untuk membuat task")

    def ev_Call(self, n, env):
        f = self.ev(n.func, env)
        args = [self.ev(a, env) for a in n.args]
        kw = {k.name: self.ev(k.value, env) for k in n.kwargs} if n.kwargs else None
        if f is None or type(f) in (int, float, str, bool, list, dict):
            nm = n.func.name if type(n.func) is A.Ident else n.func.name if type(n.func) is A.Member else "nilai"
            raise rt_err(f"'{nm}' bukan fungsi (bertipe {type_name(f)})", "TypeError", "R0214")
        return self.call(f, args, kw)

    def ev_Match(self, n, env):
        v = self.ev(n.subject, env)
        for arm in n.arms:
            e = Env(env)
            if self.match(arm.pat, v, e):
                if arm.guard is not None and not self.need_bool(self.ev(arm.guard, e), "guard"):
                    continue
                if arm.is_block:
                    return self.exec_block(arm.body, e)
                return self.ev(arm.body, e)
        raise rt_err(f"tidak ada pola mtch yang cocok untuk {to_repr(v)}", "MatchError", "R0215")

    def match(self, p, v, env):
        t = type(p)
        if t is A.PWild: return True
        if t is A.PBind:
            env.vars[p.name] = v; return True
        if t is A.PLit:
            return q_eq(p.value, v) if (p.value is None or type(p.value) is not str or type(v) is str) else False
        if t is A.PRange:
            if type(v) not in (int, float) or type(v) is bool: return False
            return p.lo <= v <= p.hi if p.inclusive else p.lo <= v < p.hi
        if t is A.POr:
            return any(self.match(a, v, env) for a in p.alts)
        if t is A.PVariant:
            name = p.name.split(".")[-1]
            if type(v) is EnumValue:
                if v.variant != name or len(v.vals) != len(p.args): return False
                return all(self.match(sp, x, env) for sp, x in zip(p.args, v.vals))
            if type(v) is Instance and v.sd.name == name:
                vals = list(v.d.values())
                if len(vals) != len(p.args): return False
                return all(self.match(sp, x, env) for sp, x in zip(p.args, vals))
            return False
        if t is A.PList:
            if type(v) is not list: return False
            k = len(p.items)
            if p.rest is None and len(v) != k: return False
            if len(v) < k: return False
            if not all(self.match(sp, x, env) for sp, x in zip(p.items, v)): return False
            if p.rest not in (None, "_"): env.vars[p.rest] = v[k:]
            return True
        return False

    # ------------------------------------------------------------ calls & types
    def call(self, f, args, kwargs=None):
        t = type(f)
        if t is QFn: return self.call_qfn(f, list(args), dict(kwargs or {}))
        if t is BoundMethod:
            if type(f.fn) is QFn: return self.call_qfn(f.fn, [f.self] + list(args), dict(kwargs or {}))
            return f.fn(f.self, *args, **(kwargs or {}))
        if t is StructDef: return self.construct(f, list(args), dict(kwargs or {}))
        if t is EnumCtor:
            fl = f.enum.variants[f.variant]
            if len(args) != len(fl):
                raise rt_err(f"{f.variant} butuh {len(fl)} nilai, diberi {len(args)}", "TypeError", "R0216")
            return EnumValue(f.enum, f.variant, list(args))
        if hasattr(f, "__qh_call__"):
            return self.native(f.__qh_call__, [list(args), dict(kwargs or {})], {})
        if callable(f):
            return self.native(f, args, kwargs or {})
        raise rt_err(f"{type_name(f)} bukan fungsi", "TypeError", "R0214")

    def native(self, f, args, kwargs):
        try:
            return f(*args, **kwargs)
        except (QichError, ReturnSig, BreakSig, ContinueSig, QichThrow, SystemExit, KeyboardInterrupt):
            raise
        except RecursionError:
            raise rt_err("stack overflow (rekursi terlalu dalam)", "ResourceLimit", "R0901")
        except Exception as e:
            nm = getattr(f, "__name__", "fungsi native")
            raise rt_err(f"{nm}: {type(e).__name__}: {e}", "NativeError", "R0300")

    def check(self, v, t, env, tb, tparams, what):
        if not self.type_ok(v, t, env, tb, tparams):
            raise rt_err(f"{what} bertipe {self.tstr(t)}, tetapi nilainya {to_repr(v)} ({type_name(v)})", "TypeError", "R0220")

    def tstr(self, t):
        s = t.name + ("<" + ", ".join(self.tstr(a) for a in t.args) + ">" if t.args else "")
        return s + ("?" if t.nullable else "")

    def type_ok(self, v, t, env, tb, tparams):
        if t.nullable and v is None: return True
        nm = t.name
        if nm in tparams:
            tag = type_name(v)
            if tag == "int" and False: pass
            if tb is None: return True
            if nm in tb: return tb[nm] == tag
            tb[nm] = tag; return True
        tv = type(v)
        if nm == "any": return True
        if nm == "int": return tv is int
        if nm in ("float", "num"): return tv is int or tv is float
        if nm == "str": return tv is str
        if nm == "bool": return tv is bool
        if nm == "nil": return v is None
        if nm == "bytes": return tv is bytes
        if nm == "fn": return tv in (QFn, BoundMethod, EnumCtor) or callable(v)
        if nm == "list":
            if tv is not list: return False
            return not t.args or all(self.type_ok(x, t.args[0], env, tb, tparams) for x in v)
        if nm == "map":
            if tv is not dict: return False
            if len(t.args) == 2:
                return all(self.type_ok(k, t.args[0], env, tb, tparams) and self.type_ok(x, t.args[1], env, tb, tparams) for k, x in v.items())
            return True
        if nm == "Result":
            return tv is EnumValue and v.enum is RESULT
        if nm == "Task": return tv is Task
        if "." in nm: return True
        e = env.lookup(nm) if env is not None else None
        if e is None:
            raise rt_err(f"tipe '{nm}' tidak dikenal", "TypeError", "R0221")
        d = e.vars[nm]
        if type(d) is StructDef: return tv is Instance and v.sd is d
        if type(d) is EnumDef: return tv is EnumValue and v.enum is d
        if isinstance(d, type): return isinstance(v, d)
        return True

    def construct(self, sd, args, kwargs):
        fs = sd.fields
        if len(args) > len(fs):
            raise rt_err(f"{sd.name}() menerima {len(fs)} field, diberi {len(args)}", "TypeError", "R0217")
        d = {}; tb = {} if sd.tparams else None
        for i, p in enumerate(fs):
            if i < len(args): v = args[i]
            elif p.name in kwargs: v = kwargs.pop(p.name)
            elif p.default is not None: v = self.ev(p.default, sd.env)
            else: raise rt_err(f"{sd.name}() kekurangan field '{p.name}'", "TypeError", "R0217")
            if p.ann is not None:
                self.check(v, p.ann, sd.env, tb, sd.tparams, f"field '{p.name}' pada {sd.name}")
            d[p.name] = v
        if kwargs:
            raise rt_err(f"{sd.name}() field tidak dikenal: {', '.join(kwargs)}", "TypeError", "R0217")
        return Instance(sd, d)

    def call_qfn(self, fn, args, kwargs):
        node = fn.node
        depth = getattr(self.tl, "depth", 0) + 1
        if depth > self.max_depth:
            raise rt_err("stack overflow (kedalaman panggilan melebihi batas)", "ResourceLimit", "R0901")
        if self.max_steps:
            self.steps += 1
            if self.steps > self.max_steps:
                raise rt_err("batas langkah eksekusi terlampaui", "ResourceLimit", "R0902")
        env = Env(fn.env)
        ps = node.params
        if len(args) > len(ps):
            raise rt_err(f"{fn.name}() menerima maksimal {len(ps)} argumen, diberi {len(args)}", "TypeError", "R0218")
        tb = {} if node.tparams else None
        tp = tuple(node.tparams)
        for i, p in enumerate(ps):
            if i < len(args):
                if p.name in kwargs:
                    raise rt_err(f"{fn.name}(): argumen '{p.name}' diberikan dua kali", "TypeError", "R0218")
                v = args[i]
            elif p.name in kwargs: v = kwargs.pop(p.name)
            elif p.default is not None: v = self.ev(p.default, fn.env)
            else: raise rt_err(f"{fn.name}() kekurangan argumen '{p.name}'", "TypeError", "R0218")
            if p.ann is not None:
                self.check(v, p.ann, fn.env, tb, tp, f"parameter '{p.name}' pada {fn.name}()")
            env.vars[p.name] = v
        if kwargs:
            raise rt_err(f"{fn.name}() argumen tidak dikenal: {', '.join(kwargs)}", "TypeError", "R0218")
        if node.is_async:
            return Task(lambda: self._run(fn, env, tb, tp))
        self.tl.depth = depth
        try:
            return self._run(fn, env, tb, tp)
        except QichError as e:
            if e.file is None and fn.module is not None: e.file = fn.module.file
            if len(e.trace) < 12: e.trace.append(fn.name)
            raise
        finally:
            self.tl.depth = depth - 1

    def _run(self, fn, env, tb, tp):
        node = fn.node
        for c in node.req:
            if not self.need_bool(self.ev(c.expr, env), "kontrak requires"):
                raise rt_err(f"kontrak 'requires' gagal di {fn.name}(): {c.text}", "ContractError", "R0230")
        try:
            if node.expr_body is not None:
                res = self.ev(node.expr_body, env)
            else:
                res = None
                self.exec_block(node.body, env)
        except ReturnSig as r:
            res = r.value
        if node.ret is not None:
            self.check(res, node.ret, fn.env, tb, tp, f"nilai kembali {fn.name}()")
        if node.ens:
            e2 = Env(env); e2.vars["result"] = res
            for c in node.ens:
                if not self.need_bool(self.ev(c.expr, e2), "kontrak ensures"):
                    raise rt_err(f"kontrak 'ensures' gagal di {fn.name}(): {c.text}", "ContractError", "R0231")
        return res
