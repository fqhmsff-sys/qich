"""Formatter: indentasi berbasis kurung, spasi trailing, baris kosong. Idempoten, menjaga komentar."""
from .lexer import lex


def format_source(src, file="<src>"):
    lex(src, file)  # validasi leksikal dulu
    lines = src.replace("\r\n", "\n").split("\n")
    out = []; depth = 0; blank = 0; in_block_comment = False; in_str = False
    for raw in lines:
        line = raw.strip()
        if in_str or in_block_comment:
            out.append(raw.rstrip()); 
            if in_block_comment and "*/" in raw: in_block_comment = False
            if in_str and raw.count('"') % 2 == 1: in_str = False
            continue
        if not line:
            blank += 1
            if blank <= 1 and out: out.append("")
            continue
        blank = 0
        # hitung kurung di luar string/komentar
        opens = closes = 0; lead_close = 0; i = 0; s = False; first = True
        while i < len(line):
            c = line[i]
            if s:
                if c == "\\": i += 2; continue
                if c == '"': s = False
            else:
                if c == '"': s = True
                elif line.startswith("//", i): break
                elif line.startswith("/*", i):
                    j = line.find("*/", i + 2)
                    if j < 0: in_block_comment = True; break
                    i = j + 2; continue
                elif c in "{[(":
                    opens += 1; first = False
                elif c in "}])":
                    closes += 1
                    if first: lead_close += 1
                else:
                    if not c.isspace(): first = False
            i += 1
        if s and line.count('"') % 2 == 1: in_str = True
        d = max(depth - lead_close, 0)
        out.append("    " * d + line)
        depth = max(depth + opens - closes, 0)
    while out and out[-1] == "": out.pop()
    return "\n".join(out) + "\n"
