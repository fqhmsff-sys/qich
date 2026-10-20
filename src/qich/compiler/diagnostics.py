"""Diagnostik yang bisa dibaca manusia."""
import os


class QichError(Exception):
    def __init__(self, msg, kind="Error", code="E0000", line=None, col=None,
                 file=None, length=1, hint=None):
        super().__init__(msg)
        if isinstance(line, str):  # pemanggil mengisi hint secara posisional
            hint, line = line, None
        self.msg = msg; self.kind = kind; self.code = code
        self.line = line; self.col = col; self.file = file
        self.length = length; self.hint = hint; self.trace = []

    def __str__(self):
        return f"{self.kind}: {self.msg}"


class Warn:
    def __init__(self, msg, code, line, col, file=None, length=1, hint=None):
        self.msg = msg; self.code = code; self.line = line; self.col = col
        self.file = file; self.length = length; self.hint = hint


def _src_lines(file, sources):
    if sources and file in sources:
        return sources[file].split("\n")
    try:
        if file and os.path.isfile(file):
            with open(file, encoding="utf-8") as f:
                return f.read().split("\n")
    except OSError:
        pass
    return []


def render(level, code, msg, file, line, col, length, hint, sources=None, trace=None):
    out = [f"{level}[{code}]: {msg}"]
    if line is not None:
        out.append(f"  --> {file or '<src>'}:{line}:{col or 1}")
        lines = _src_lines(file, sources)
        if 1 <= line <= len(lines):
            w = len(str(line))
            out.append(" " * (w + 1) + "|")
            out.append(f"{line:>{w}} | {lines[line - 1]}")
            out.append(" " * (w + 1) + "| " + " " * max((col or 1) - 1, 0) + "^" * max(length, 1))
    if hint:
        out.append(f"  = bantuan: {hint}")
    if trace:
        out.append("  = jejak: " + " <- ".join(trace))
    return "\n".join(out)


def render_error(e, sources=None):
    msg = e.msg if e.kind in ("SyntaxError", "SemanticError") else f"{e.kind}: {e.msg}"
    return render("error", e.code, msg, e.file, e.line, e.col, e.length, e.hint, sources, e.trace)


def render_warn(w, sources=None):
    return render("warning", w.code, w.msg, w.file, w.line, w.col, w.length, w.hint, sources)
