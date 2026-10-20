"""Lexer Qich."""
import re
import math
from .diagnostics import QichError

MAX_SRC = 4_000_000
KEYWORDS = {"let", "fn", "rtrn", "if", "else", "whl", "for", "in", "brk", "cnt", "strct",
            "enm", "mtch", "use", "try", "catch", "throw", "async", "await", "true",
            "false", "nil", "requires", "ensures"}
OPS3 = ("..=",)
OPS2 = ("==", "!=", "<=", ">=", "&&", "||", "=>", "->", "..", "+=", "-=", "*=", "/=", "%=")
OPS1 = "+-*/%<>=!?:,.;()[]{}|"
NUM_RE = re.compile(r"0[xX][0-9a-fA-F_]+|\d[\d_]*(\.\d[\d_]*)?([eE][+-]?\d+)?")
ID_RE = re.compile(r"[^\W\d]\w*")
ESC = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", '"': '"', "'": "'", "{": "{", "}": "}"}


class Tok:
    __slots__ = ("k", "v", "line", "col", "nl", "pos", "end")

    def __init__(self, k, v, line, col, nl, pos, end):
        self.k = k; self.v = v; self.line = line; self.col = col
        self.nl = nl; self.pos = pos; self.end = end

    def __repr__(self):
        return f"Tok({self.k},{self.v!r},{self.line}:{self.col})"


def lex(src, file="<src>", base_line=1, base_col=1):
    if len(src) > MAX_SRC:
        raise QichError("sumber terlalu besar", "SyntaxError", "E0003", 1, 1, file)
    toks = []; docs = {}
    i = 0; n = len(src); line = base_line; ls = -(base_col - 1); nl = True

    def err(msg, pos, code="E0002", length=1, hint=None):
        raise QichError(msg, "SyntaxError", code, line, pos - ls + 1, file, length, hint)

    def loc(pos):
        k = src.rfind("\n", 0, pos)
        return (base_line + src.count("\n", 0, pos), (pos - k) if k >= 0 else pos + base_col)

    while i < n:
        c = src[i]
        if c == "\n":
            line += 1; ls = i + 1; nl = True; i += 1; continue
        if c in " \t\r":
            i += 1; continue
        if c == "/" and src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            if src.startswith("///", i) and not src.startswith("////", i):
                docs[line] = src[i + 3:j].strip()
            i = j; continue
        if c == "/" and src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                err("komentar blok tidak ditutup", i)
            cnt = src.count("\n", i, j + 2)
            if cnt:
                line += cnt; ls = src.rfind("\n", i, j + 2) + 1; nl = True
            i = j + 2; continue
        col = i - ls + 1
        if c.isdigit():
            m = NUM_RE.match(src, i)
            txt = m.group(0).replace("_", "")
            if txt[:2] in ("0x", "0X"):
                val = int(txt, 16)
            elif "." in txt or "e" in txt or "E" in txt:
                val = float(txt)
                if not math.isfinite(val):
                    err("angka di luar jangkauan", i, length=len(txt))
            else:
                if len(txt) > 4000:
                    err("angka terlalu panjang", i)
                val = int(txt)
            toks.append(Tok("num", val, line, col, nl, i, m.end())); nl = False
            i = m.end(); continue
        if c == '"' or (c == "f" and src.startswith('f"', i) and not (i > 0 and (src[i - 1].isalnum() or src[i - 1] == "_"))):
            fmt = c == "f"
            start = i
            i += 2 if fmt else 1
            parts = []; buf = []
            while True:
                if i >= n:
                    err("string tidak ditutup", start, "E0004", hint='tambahkan tanda kutip " penutup')
                ch = src[i]
                if ch == '"':
                    i += 1; break
                if ch == "\\":
                    i += 1
                    if i >= n:
                        err("escape tidak lengkap", i - 1)
                    e = src[i]
                    if e == "u":
                        hx = src[i + 1:i + 5]
                        if len(hx) != 4 or not re.fullmatch(r"[0-9a-fA-F]{4}", hx):
                            err("escape \\u butuh 4 digit hex", i)
                        buf.append(chr(int(hx, 16))); i += 5; continue
                    if e not in ESC:
                        err(f"escape tidak dikenal: \\{e}", i - 1, length=2)
                    buf.append(ESC[e]); i += 1; continue
                if fmt and ch == "{":
                    if src.startswith("{{", i):
                        buf.append("{"); i += 2; continue
                    depth = 1; j = i + 1; instr = False
                    while j < n and depth > 0:
                        d = src[j]
                        if d == '"':
                            instr = not instr
                        elif not instr:
                            if d == "{": depth += 1
                            elif d == "}": depth -= 1
                        j += 1
                    if depth:
                        err("interpolasi '{' tidak ditutup", i)
                    if buf:
                        parts.append("".join(buf)); buf = []
                    ln, cl = loc(i + 1)
                    parts.append(("expr", src[i + 1:j - 1], ln, cl))
                    i = j; continue
                if fmt and ch == "}" and src.startswith("}}", i):
                    buf.append("}"); i += 2; continue
                buf.append(ch); i += 1
            if fmt:
                if buf:
                    parts.append("".join(buf))
                toks.append(Tok("fstr", parts, line, col, nl, start, i))
            else:
                toks.append(Tok("str", "".join(buf), line, col, nl, start, i))
            nl = False
            cnt = src.count("\n", start, i)
            if cnt:
                line += cnt; ls = src.rfind("\n", start, i) + 1
            continue
        m = ID_RE.match(src, i)
        if m:
            w = m.group(0)
            toks.append(Tok("kw" if w in KEYWORDS else "id", w, line, col, nl, i, m.end())); nl = False
            i = m.end(); continue
        if src.startswith(OPS3[0], i):
            toks.append(Tok("op", "..=", line, col, nl, i, i + 3)); nl = False; i += 3; continue
        two = src[i:i + 2]
        if two in OPS2:
            toks.append(Tok("op", two, line, col, nl, i, i + 2)); nl = False; i += 2; continue
        if c in OPS1:
            toks.append(Tok("op", c, line, col, nl, i, i + 1)); nl = False; i += 1; continue
        err(f"karakter tidak dikenal {c!r}", i, "E0005")
    toks.append(Tok("eof", None, line, i - ls + 1, True, n, n))
    return toks, docs
