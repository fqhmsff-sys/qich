"""Parser Qich -> AST."""
from . import ast as A
from .lexer import lex
from .diagnostics import QichError

MAX_DEPTH = 160
CMP = {"<", ">", "<=", ">="}
ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%="}


class Parser:
    def __init__(self, toks, docs, src, file):
        self.t = toks; self.i = 0; self.docs = docs; self.src = src; self.file = file; self.depth = 0

    # ---- util
    @property
    def cur(self):
        return self.t[self.i]

    def peek(self, k=1):
        return self.t[min(self.i + k, len(self.t) - 1)]

    def next(self):
        t = self.t[self.i]
        if t.k != "eof":
            self.i += 1
        return t

    def err(self, msg, tok=None, code="E0010", hint=None):
        tok = tok or self.cur
        raise QichError(msg, "SyntaxError", code, tok.line, tok.col, self.file, max(1, tok.end - tok.pos), hint)

    def desc(self, t):
        return "akhir file" if t.k == "eof" else f"'{t.v}'" if t.k != "str" else "string"

    def is_op(self, v):
        t = self.cur
        return t.k == "op" and t.v == v

    def is_kw(self, v):
        t = self.cur
        return t.k == "kw" and t.v == v

    def accept_op(self, v):
        if self.is_op(v):
            return self.next()
        return None

    def expect_op(self, v):
        if not self.is_op(v):
            hint = None
            if v == "}":
                hint = "ada kurung '{' yang belum ditutup"
            self.err(f"diharapkan '{v}' tetapi menemukan {self.desc(self.cur)}", hint=hint)
        return self.next()

    def expect_kw(self, v):
        if not self.is_kw(v):
            self.err(f"diharapkan '{v}' tetapi menemukan {self.desc(self.cur)}")
        return self.next()

    def expect_id(self, what="nama"):
        t = self.cur
        if t.k != "id":
            self.err(f"diharapkan {what} tetapi menemukan {self.desc(t)}")
        return self.next()

    def enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            self.err("nesting terlalu dalam", code="E0011")

    def leave(self):
        self.depth -= 1

    def doc_for(self, line):
        out = []; l = line - 1
        while l in self.docs:
            out.append(self.docs[l]); l -= 1
        return "\n".join(reversed(out))

    def loc(self, tok):
        return {"line": tok.line, "col": tok.col}

    def starts_expr(self, t):
        if t.k in ("num", "str", "fstr", "id"):
            return True
        if t.k == "kw":
            return t.v in ("true", "false", "nil", "fn", "mtch", "await", "async")
        if t.k == "op":
            return t.v in ("(", "[", "{", "!", "-")
        return False

    # ---- program / statements
    def parse_program(self):
        body = []
        while self.cur.k != "eof":
            if self.accept_op(";"):
                continue
            body.append(self.statement())
        return A.Program(body=body, line=1, col=1)

    def block(self):
        self.expect_op("{")
        out = []
        while not self.is_op("}"):
            if self.cur.k == "eof":
                self.err("kurung '}' tidak ditutup", code="E0012", hint="tambahkan '}' di akhir blok")
            if self.accept_op(";"):
                continue
            out.append(self.statement())
        self.next()
        return out

    def statement(self):
        self.enter()
        try:
            return self._statement()
        finally:
            self.leave()

    def _statement(self):
        t = self.cur
        loc = self.loc(t)
        if t.k == "kw":
            v = t.v
            if v == "use": return self.parse_use()
            if v == "let": return self.parse_let()
            if v == "fn" and self.peek().k == "id": return self.parse_fn()
            if v == "async" and self.peek().k == "kw" and self.peek().v == "fn" and self.peek(2).k == "id":
                return self.parse_fn()
            if v == "rtrn":
                self.next()
                val = None
                if not self.cur.nl and self.starts_expr(self.cur):
                    val = self.expr()
                return A.Return(value=val, **loc)
            if v == "brk": self.next(); return A.Break(**loc)
            if v == "cnt": self.next(); return A.Continue(**loc)
            if v == "if": return self.parse_if()
            if v == "whl":
                self.next(); c = self.expr(); return A.While(cond=c, body=self.block(), **loc)
            if v == "for":
                self.next(); names = [self.expect_id("nama variabel").v]
                while self.accept_op(","):
                    names.append(self.expect_id("nama variabel").v)
                self.expect_kw("in")
                it = self.expr()
                return A.For(vars=names, iter=it, body=self.block(), **loc)
            if v == "strct": return self.parse_strct()
            if v == "enm": return self.parse_enm()
            if v == "try":
                self.next(); body = self.block(); self.expect_kw("catch")
                var = None
                if self.cur.k == "id":
                    var = self.next().v
                return A.Try(body=body, var=var, handler=self.block(), **loc)
            if v == "throw":
                self.next(); return A.Throw(value=self.expr(), **loc)
        if t.k == "op" and t.v == "{":
            return A.Block(body=self.block(), **loc)
        e = self.expr()
        if self.cur.k == "op" and self.cur.v in ASSIGN_OPS and not self.cur.nl:
            op = self.next().v
            if not isinstance(e, (A.Ident, A.Index, A.Member)):
                self.err("sisi kiri assignment tidak valid", t, "E0013",
                         hint="hanya variabel, indeks, atau anggota yang bisa diisi")
            return A.Assign(target=e, op=op, value=self.expr(), **loc)
        return A.ExprStmt(expr=e, **loc)

    def parse_use(self):
        t = self.next()
        eco = self.cur
        if eco.k not in ("id", "kw"):
            self.err("diharapkan nama ekosistem setelah 'use' (contoh: use py:torch)")
        self.next()
        self.expect_op(":")
        parts = []
        while True:
            if self.cur.k not in ("id", "kw"):
                self.err("diharapkan nama library setelah ':'")
            parts.append(self.next().v)
            if self.is_op(".") or self.is_op("/"):
                self.next(); continue
            break
        alias = None
        if self.cur.k == "id" and self.cur.v == "as" and not self.cur.nl:
            self.next(); alias = self.expect_id("alias").v
        return A.Use(eco=eco.v, lib=".".join(parts), alias=alias, **self.loc(t))

    def parse_let(self):
        t = self.next()
        name = self.expect_id("nama variabel").v
        ann = None
        if self.accept_op(":"):
            ann = self.type_()
        val = None
        if self.accept_op("="):
            val = self.expr()
        return A.Let(name=name, ann=ann, value=val, **self.loc(t))

    def parse_if(self):
        t = self.next()
        c = self.expr()
        then = self.block()
        els = None
        if self.is_kw("else"):
            self.next()
            if self.is_kw("if"):
                els = [self.parse_if()]
            else:
                els = self.block()
        return A.If(cond=c, then=then, els=els, **self.loc(t))

    def type_(self):
        t = self.cur
        if t.k not in ("id",) and not (t.k == "kw" and t.v in ("fn", "nil")):
            self.err(f"diharapkan tipe tetapi menemukan {self.desc(t)}")
        self.next()
        name = t.v
        while self.is_op(".") and self.peek().k == "id":
            self.next(); name += "." + self.next().v
        args = []
        if self.is_op("<"):
            self.next()
            args.append(self.type_())
            while self.accept_op(","):
                args.append(self.type_())
            self.expect_op(">")
        nullable = bool(self.accept_op("?"))
        return A.Type(name=name, args=args, nullable=nullable, **self.loc(t))

    def params(self):
        self.expect_op("(")
        ps = []
        while not self.is_op(")"):
            t = self.expect_id("nama parameter")
            ann = self.type_() if self.accept_op(":") else None
            default = self.ternary() if self.accept_op("=") else None
            ps.append(A.Param(name=t.v, ann=ann, default=default, **self.loc(t)))
            if not self.accept_op(","):
                break
        self.expect_op(")")
        return ps

    def parse_fn(self, expr=False):
        is_async = False
        if self.is_kw("async"):
            self.next(); is_async = True
        t = self.expect_kw("fn")
        name = None
        if not expr:
            name = self.expect_id("nama fungsi").v
        tparams = []
        if self.accept_op("<"):
            tparams.append(self.expect_id("nama tipe").v)
            while self.accept_op(","):
                tparams.append(self.expect_id("nama tipe").v)
            self.expect_op(">")
        ps = self.params()
        ret = self.type_() if self.accept_op("->") else None
        req = []; ens = []
        while self.is_kw("requires") or self.is_kw("ensures"):
            k = self.next().v
            first = self.cur
            e = self.ternary()
            last = self.t[self.i - 1]
            c = A.Contract(expr=e, text=self.src[first.pos:last.end].strip(), **self.loc(first))
            (req if k == "requires" else ens).append(c)
        body = None; eb = None
        if self.is_kw("rtrn"):
            self.next(); self.expect_op("=>"); eb = self.expr()
        elif self.is_op("=>"):
            self.next(); eb = self.expr()
        else:
            body = self.block()
        doc = self.doc_for(t.line) if not expr else ""
        return A.Fn(name=name, params=ps, ret=ret, body=body, expr_body=eb, is_async=is_async,
                    tparams=tparams, req=req, ens=ens, doc=doc, **self.loc(t))

    def members(self, allow_fields):
        flds = []; methods = []
        self.expect_op("{")
        while not self.is_op("}"):
            if self.cur.k == "eof":
                self.err("kurung '}' tidak ditutup", code="E0012")
            if self.accept_op(",") or self.accept_op(";"):
                continue
            if self.is_kw("fn") or self.is_kw("async"):
                methods.append(self.parse_fn())
            elif allow_fields:
                t = self.expect_id("nama field")
                ann = self.type_() if self.accept_op(":") else None
                d = self.ternary() if self.accept_op("=") else None
                flds.append(A.Param(name=t.v, ann=ann, default=d, **self.loc(t)))
            else:
                self.err("diharapkan 'fn' atau '}'")
        self.next()
        return flds, methods

    def parse_strct(self):
        t = self.next()
        name = self.expect_id("nama strct").v
        tparams = []
        if self.accept_op("<"):
            tparams.append(self.expect_id("nama tipe").v)
            while self.accept_op(","):
                tparams.append(self.expect_id("nama tipe").v)
            self.expect_op(">")
        flds, methods = self.members(True)
        return A.Strct(name=name, fields=flds, methods=methods, tparams=tparams,
                       doc=self.doc_for(t.line), **self.loc(t))

    def parse_enm(self):
        t = self.next()
        name = self.expect_id("nama enm").v
        self.expect_op("{")
        variants = []; methods = []
        while not self.is_op("}"):
            if self.cur.k == "eof":
                self.err("kurung '}' tidak ditutup", code="E0012")
            if self.accept_op(",") or self.accept_op(";"):
                continue
            if self.is_kw("fn") or self.is_kw("async"):
                methods.append(self.parse_fn()); continue
            vt = self.expect_id("nama varian")
            flds = []
            if self.accept_op("("):
                while not self.is_op(")"):
                    ft = self.expect_id("nama field")
                    ann = self.type_() if self.accept_op(":") else None
                    flds.append(A.Param(name=ft.v, ann=ann, default=None, **self.loc(ft)))
                    if not self.accept_op(","):
                        break
                self.expect_op(")")
            variants.append(A.Variant(name=vt.v, fields=flds, **self.loc(vt)))
        self.next()
        return A.Enm(name=name, variants=variants, methods=methods, doc=self.doc_for(t.line), **self.loc(t))

    # ---- expressions
    def expr(self):
        self.enter()
        try:
            return self.ternary()
        finally:
            self.leave()

    def ternary(self):
        c = self.or_()
        if self.is_op("?"):
            t = self.next()
            a = self.ternary()
            self.expect_op(":")
            b = self.ternary()
            return A.Ternary(cond=c, a=a, b=b, **self.loc(t))
        return c

    def bin_loop(self, sub, ops):
        left = sub()
        while self.cur.k == "op" and self.cur.v in ops and not (self.cur.nl and self.cur.v in ("+", "-")):
            t = self.next()
            right = sub()
            left = A.Binary(op=t.v, left=left, right=right, **self.loc(t))
        return left

    def or_(self): return self.bin_loop(self.and_, {"||"})
    def and_(self): return self.bin_loop(self.eq, {"&&"})
    def eq(self): return self.bin_loop(self.cmp, {"==", "!="})

    def cmp(self):
        left = self.range_()
        while (self.cur.k == "op" and self.cur.v in CMP) or (self.cur.k == "kw" and self.cur.v == "in"):
            t = self.next()
            right = self.range_()
            left = A.Binary(op=t.v, left=left, right=right, **self.loc(t))
        return left

    def range_(self):
        left = self.add()
        if self.is_op("..") or self.is_op("..="):
            t = self.next()
            right = self.add()
            return A.Range(start=left, end=right, inclusive=(t.v == "..="), **self.loc(t))
        return left

    def add(self): return self.bin_loop(self.mul, {"+", "-"})
    def mul(self): return self.bin_loop(self.unary, {"*", "/", "%"})

    def unary(self):
        t = self.cur
        if t.k == "op" and t.v in ("!", "-"):
            self.next()
            self.enter()
            try:
                return A.Unary(op=t.v, operand=self.unary(), **self.loc(t))
            finally:
                self.leave()
        if t.k == "kw" and t.v == "await":
            self.next()
            return A.Await(expr=self.unary(), **self.loc(t))
        return self.postfix()

    def args(self):
        args = []; kws = []
        self.expect_op("(")
        while not self.is_op(")"):
            if self.cur.k == "id" and self.peek().k == "op" and self.peek().v == ":":
                nt = self.next(); self.next()
                kws.append(A.Kw(name=nt.v, value=self.ternary(), **self.loc(nt)))
            else:
                if kws:
                    self.err("argumen posisi tidak boleh setelah argumen bernama")
                args.append(self.ternary())
            if not self.accept_op(","):
                break
        self.expect_op(")")
        return args, kws

    def postfix(self):
        e = self.primary()
        while True:
            t = self.cur
            if t.k != "op":
                break
            if t.v == "(" and not t.nl:
                a, k = self.args()
                e = A.Call(func=e, args=a, kwargs=k, **self.loc(t))
            elif t.v == "[" and not t.nl:
                self.next()
                idx = self.expr()
                self.expect_op("]")
                e = A.Index(obj=e, idx=idx, **self.loc(t))
            elif t.v == ".":
                self.next()
                nt = self.cur
                if nt.k not in ("id", "kw"):
                    self.err("diharapkan nama anggota setelah '.'")
                self.next()
                e = A.Member(obj=e, name=nt.v, **self.loc(nt))
            elif t.v == "?":
                n2 = self.peek()
                if n2.nl or not self.starts_expr(n2):
                    self.next()
                    e = A.TryOp(expr=e, **self.loc(t))
                else:
                    break
            else:
                break
        return e

    def primary(self):
        t = self.cur
        loc = self.loc(t)
        if t.k == "num":
            self.next(); return A.Num(value=t.v, **loc)
        if t.k == "str":
            self.next(); return A.Str(value=t.v, **loc)
        if t.k == "fstr":
            self.next()
            parts = []
            for p in t.v:
                if isinstance(p, str):
                    parts.append(p)
                else:
                    _, text, ln, cl = p
                    toks, docs = lex(text, self.file, ln, cl)
                    sub = Parser(toks, docs, text, self.file)
                    sub.depth = self.depth
                    e = sub.expr()
                    if sub.cur.k != "eof":
                        sub.err("ekspresi interpolasi tidak valid")
                    parts.append(e)
            return A.FStr(parts=parts, **loc)
        if t.k == "id":
            self.next(); return A.Ident(name=t.v, **loc)
        if t.k == "kw":
            if t.v == "true": self.next(); return A.Bool(value=True, **loc)
            if t.v == "false": self.next(); return A.Bool(value=False, **loc)
            if t.v == "nil": self.next(); return A.Nil(**loc)
            if t.v == "fn" or t.v == "async":
                return A.FnExpr(fn=self.parse_fn(expr=True), **loc)
            if t.v == "mtch":
                return self.parse_match()
        if t.k == "op":
            if t.v == "(":
                self.next()
                e = self.expr()
                self.expect_op(")")
                return e
            if t.v == "[":
                self.next()
                items = []
                while not self.is_op("]"):
                    items.append(self.ternary())
                    if not self.accept_op(",") and not self.cur.nl:
                        break
                self.expect_op("]")
                return A.ListLit(items=items, **loc)
            if t.v == "{":
                return self.parse_map()
        self.err(f"ekspresi diharapkan tetapi menemukan {self.desc(t)}", t, "E0014")

    def parse_map(self):
        t = self.next()
        entries = []
        while not self.is_op("}"):
            k = self.cur
            if k.k == "id" and self.peek().k == "op" and self.peek().v == ":":
                self.next(); key = A.Str(value=k.v, **self.loc(k))
            else:
                key = self.or_()
            self.expect_op(":")
            val = self.ternary()
            entries.append(A.Entry(key=key, value=val, **self.loc(k)))
            if not self.accept_op(",") and not self.cur.nl:
                break
        self.expect_op("}")
        return A.MapLit(entries=entries, **self.loc(t))

    def parse_match(self):
        t = self.next()
        subj = self.expr()
        self.expect_op("{")
        arms = []
        while not self.is_op("}"):
            if self.cur.k == "eof":
                self.err("kurung '}' tidak ditutup", code="E0012")
            pt = self.cur
            pat = self.pattern()
            guard = None
            if self.is_kw("if"):
                self.next(); guard = self.ternary()
            self.expect_op("=>")
            if self.is_op("{"):
                body = self.block(); blk = True
            else:
                body = self.ternary(); blk = False
            arms.append(A.Arm(pat=pat, guard=guard, body=body, is_block=blk, **self.loc(pt)))
            self.accept_op(",")
        self.next()
        return A.Match(subject=subj, arms=arms, **self.loc(t))

    def pattern(self):
        first = self.pat_alt()
        if self.is_op("|"):
            alts = [first]
            while self.accept_op("|"):
                alts.append(self.pat_alt())
            return A.POr(alts=alts, line=first.line, col=first.col)
        return first

    def pat_lit(self):
        t = self.cur
        neg = False
        if t.k == "op" and t.v == "-" and self.peek().k == "num":
            self.next(); neg = True; t = self.cur
        if t.k == "num":
            self.next(); return -t.v if neg else t.v
        if t.k == "str":
            self.next(); return t.v
        return None

    def pat_alt(self):
        t = self.cur
        loc = self.loc(t)
        if t.k == "num" or t.k == "str" or (t.k == "op" and t.v == "-"):
            lo = self.pat_lit()
            if lo is None:
                self.err("pola tidak valid")
            if (self.is_op("..") or self.is_op("..=")) and isinstance(lo, (int, float)):
                inc = self.next().v == "..="
                hi = self.pat_lit()
                if hi is None:
                    self.err("batas atas range tidak valid")
                return A.PRange(lo=lo, hi=hi, inclusive=inc, **loc)
            return A.PLit(value=lo, **loc)
        if t.k == "kw" and t.v in ("true", "false", "nil"):
            self.next()
            return A.PLit(value={"true": True, "false": False, "nil": None}[t.v], **loc)
        if t.k == "op" and t.v == "(":
            self.next(); p = self.pattern(); self.expect_op(")"); return p
        if t.k == "op" and t.v == "[":
            self.next()
            items = []; rest = None
            while not self.is_op("]"):
                if self.is_op(".."):
                    self.next()
                    rest = self.next().v if self.cur.k == "id" else "_"
                else:
                    items.append(self.pattern())
                if not self.accept_op(","):
                    break
            self.expect_op("]")
            return A.PList(items=items, rest=rest, **loc)
        if t.k == "id":
            self.next()
            name = t.v
            while self.is_op(".") and self.peek().k == "id":
                self.next(); name += "." + self.next().v
            if self.is_op("("):
                self.next()
                args = []
                while not self.is_op(")"):
                    args.append(self.pattern())
                    if not self.accept_op(","):
                        break
                self.expect_op(")")
                return A.PVariant(name=name, args=args, **loc)
            if name == "_":
                return A.PWild(**loc)
            if name[0].isupper() or "." in name:
                return A.PVariant(name=name, args=[], **loc)
            return A.PBind(name=name, **loc)
        self.err(f"pola tidak valid: {self.desc(t)}")


def parse(src, file="<src>"):
    toks, docs = lex(src, file)
    try:
        return Parser(toks, docs, src, file).parse_program()
    except RecursionError:
        raise QichError("nesting terlalu dalam", "SyntaxError", "E0011", 1, 1, file)
