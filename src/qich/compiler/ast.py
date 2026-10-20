"""AST Qich + serialisasi/verifikasi untuk artifact .qhc."""
from dataclasses import dataclass, fields
import math

NODES = {}


@dataclass(kw_only=True)
class Node:
    line: int = 0
    col: int = 0


def node(cls):
    cls = dataclass(kw_only=True)(cls)
    NODES[cls.__name__] = cls
    return cls


@node
class Program(Node): body: list
@node
class Type(Node): name: str; args: list; nullable: bool
@node
class Param(Node): name: str; ann: object; default: object
@node
class Contract(Node): expr: object; text: str
@node
class Use(Node): eco: str; lib: str; alias: object
@node
class Let(Node): name: str; ann: object; value: object
@node
class Assign(Node): target: object; op: str; value: object
@node
class ExprStmt(Node): expr: object
@node
class Fn(Node):
    name: object; params: list; ret: object; body: object; expr_body: object
    is_async: bool; tparams: list; req: list; ens: list; doc: str
@node
class Return(Node): value: object
@node
class Break(Node): pass
@node
class Continue(Node): pass
@node
class If(Node): cond: object; then: list; els: object
@node
class While(Node): cond: object; body: list
@node
class For(Node): vars: list; iter: object; body: list
@node
class Strct(Node): name: str; fields: list; methods: list; tparams: list; doc: str
@node
class Variant(Node): name: str; fields: list
@node
class Enm(Node): name: str; variants: list; methods: list; doc: str
@node
class Try(Node): body: list; var: object; handler: list
@node
class Throw(Node): value: object
@node
class Block(Node): body: list
@node
class Num(Node): value: object
@node
class Str(Node): value: str
@node
class FStr(Node): parts: list
@node
class Bool(Node): value: bool
@node
class Nil(Node): pass
@node
class Ident(Node): name: str
@node
class ListLit(Node): items: list
@node
class Entry(Node): key: object; value: object
@node
class MapLit(Node): entries: list
@node
class Unary(Node): op: str; operand: object
@node
class Binary(Node): op: str; left: object; right: object
@node
class Ternary(Node): cond: object; a: object; b: object
@node
class Kw(Node): name: str; value: object
@node
class Call(Node): func: object; args: list; kwargs: list
@node
class Index(Node): obj: object; idx: object
@node
class Member(Node): obj: object; name: str
@node
class TryOp(Node): expr: object
@node
class Await(Node): expr: object
@node
class Range(Node): start: object; end: object; inclusive: bool
@node
class Arm(Node): pat: object; guard: object; body: object; is_block: bool
@node
class Match(Node): subject: object; arms: list
@node
class FnExpr(Node): fn: object
@node
class PLit(Node): value: object
@node
class PWild(Node): pass
@node
class PBind(Node): name: str
@node
class PVariant(Node): name: str; args: list
@node
class PList(Node): items: list; rest: object
@node
class POr(Node): alts: list
@node
class PRange(Node): lo: object; hi: object; inclusive: bool


def to_dict(n):
    if isinstance(n, Node):
        d = {"t": type(n).__name__}
        for f in fields(n):
            d[f.name] = to_dict(getattr(n, f.name))
        return d
    if isinstance(n, list):
        return [to_dict(x) for x in n]
    return n


def from_dict(d, depth=0):
    """Verifier: menolak node tak dikenal, field asing, tipe salah, nesting berlebihan."""
    if depth > 400:
        raise ValueError("nesting terlalu dalam")
    if isinstance(d, dict):
        cls = NODES.get(d.get("t"))
        if cls is None:
            raise ValueError("node tidak dikenal: %r" % (d.get("t"),))
        spec = {f.name: f.type for f in fields(cls)}
        kw = {}
        for k, v in d.items():
            if k == "t":
                continue
            if k not in spec:
                raise ValueError("field asing %r pada %s" % (k, cls.__name__))
            val = from_dict(v, depth + 1)
            ann = spec[k]
            if ann in (str, list) and not isinstance(val, ann):
                raise ValueError("tipe field %s.%s salah" % (cls.__name__, k))
            if ann is int and (not isinstance(val, int) or isinstance(val, bool)):
                raise ValueError("tipe field %s.%s salah" % (cls.__name__, k))
            if ann is bool and not isinstance(val, bool):
                raise ValueError("tipe field %s.%s salah" % (cls.__name__, k))
            kw[k] = val
        try:
            return cls(**kw)
        except TypeError as e:
            raise ValueError(str(e))
    if isinstance(d, list):
        return [from_dict(x, depth + 1) for x in d]
    if isinstance(d, float):
        if not math.isfinite(d):
            raise ValueError("angka AST harus finite")
        return d
    if d is None or isinstance(d, (str, int, bool)):
        return d
    raise ValueError("nilai tidak valid")
