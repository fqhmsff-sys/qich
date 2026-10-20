"""Generator dokumentasi dari komentar '///'."""
from . import ast as A
from .parser import parse


def sig(f):
    ps = ", ".join(p.name + (": " + p.ann.name if p.ann else "") for p in f.params)
    return f"fn {f.name}({ps})" + (f" -> {f.ret.name}" if f.ret else "")


def generate(src, file):
    prog = parse(src, file)
    out = [f"# `{file}`\n"]
    for s in prog.body:
        if type(s) is A.Fn:
            out.append(f"## `{sig(s)}`\n\n{s.doc or '_(tanpa dokumentasi)_'}\n")
        elif type(s) is A.Strct:
            out.append(f"## strct `{s.name}`\n\n{s.doc or '_(tanpa dokumentasi)_'}\n")
            out.append("Field: " + ", ".join(f"`{p.name}`" for p in s.fields) + "\n")
            for m in s.methods: out.append(f"### `{sig(m)}`\n\n{m.doc or ''}\n")
        elif type(s) is A.Enm:
            out.append(f"## enm `{s.name}`\n\n{s.doc or '_(tanpa dokumentasi)_'}\n")
            out.append("Varian: " + ", ".join(f"`{v.name}`" for v in s.variants) + "\n")
    return "\n".join(out)
