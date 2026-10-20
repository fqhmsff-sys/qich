"""qapp: UI deklaratif, lifecycle, storage, dan target render.

Status: render teks & HTML (TESTED, headless). Jendela desktop via tkinter (IMPLEMENTED, tidak teruji di sandbox).
Generator Kotlin (Android) & Swift (iOS/macOS): menghasilkan source UI statis (IMPLEMENTED, belum dikompilasi di sandbox);
handler event Qich di Android/iOS membutuhkan runtime tertanam (PLANNED).
"""
import html as _html
import json
import os
import re
from ..compiler.diagnostics import QichError
from ..runtime.values import Ok, Err, make_error, to_str


def _err(msg): return QichError(msg, "ValueError", "R0420")


class Widget:
    __qh__ = {"kind", "props", "children"}

    def __init__(self, kind, props=None, children=None):
        self.kind = kind; self.props = props or {}; self.children = children or []

    def __qh_repr__(self): return f"<Widget {self.kind}>"


def Text(s): return Widget("text", {"text": to_str(s)})


def Button(label, on_click=None):
    return Widget("button", {"label": to_str(label), "on_click": on_click})


def Input(name, value="", on_change=None, placeholder=""):
    return Widget("input", {"name": name, "value": to_str(value), "on_change": on_change, "placeholder": placeholder})


def _box(kind, children):
    if type(children) is not list or not all(isinstance(c, Widget) for c in children):
        raise _err(f"{kind}() butuh list Widget")
    return Widget(kind, {}, children)


def Column(children): return _box("column", children)
def Row(children): return _box("row", children)


class State:
    __qh__ = {"get", "set"}

    def __init__(self, v=None): self.v = v; self.subs = []
    def get(self): return self.v

    def set(self, v):
        self.v = v
        for s in list(self.subs): s()


def _walk(w):
    yield w
    for c in w.children: yield from _walk(c)


def _text(w, ind=0):
    pad = "  " * ind
    if w.kind == "text": return [pad + w.props["text"]]
    if w.kind == "button": return [pad + "[" + w.props["label"] + "]"]
    if w.kind == "input": return [pad + f"<{w.props['name']}: {w.props['value']}>"]
    if w.kind == "row":
        return [pad + " | ".join(l.strip() for c in w.children for l in _text(c))]
    return [l for c in w.children for l in _text(c, ind)]


def _to_html(w):
    e = _html_escape
    if w.kind == "text": return f"<p>{e(w.props['text'])}</p>"
    if w.kind == "button": return f"<button>{e(w.props['label'])}</button>"
    if w.kind == "input": return f"<input name=\"{e(w.props['name'])}\" value=\"{e(w.props['value'])}\" placeholder=\"{e(w.props['placeholder'])}\">"
    inner = "".join(_to_html(c) for c in w.children)
    return f"<div style=\"display:flex;flex-direction:{'row' if w.kind == 'row' else 'column'};gap:8px\">{inner}</div>"


def _html_escape(s): return _html.escape(str(s), quote=True)


def _kt(s): return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("\n", "\\n") + '"'
def _sw(s): return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _kotlin(w, name, lines, counter):
    counter[0] += 1; v = f"v{counter[0]}"
    if w.kind == "text":
        lines.append(f"        val {v} = TextView(this).apply {{ text = {_kt(w.props['text'])} }}")
    elif w.kind == "button":
        lines.append(f"        val {v} = Button(this).apply {{ text = {_kt(w.props['label'])}; setOnClickListener {{ /* handler: runtime Qich tertanam (PLANNED) */ }} }}")
    elif w.kind == "input":
        lines.append(f"        val {v} = EditText(this).apply {{ setText({_kt(w.props['value'])}); hint = {_kt(w.props['placeholder'])} }}")
    else:
        lines.append(f"        val {v} = LinearLayout(this).apply {{ orientation = LinearLayout.{'HORIZONTAL' if w.kind == 'row' else 'VERTICAL'} }}")
        for c in w.children:
            cv = _kotlin(c, name, lines, counter)
            lines.append(f"        {v}.addView({cv})")
    return v


def _swift(w, ind):
    p = "    " * ind
    if w.kind == "text": return [p + f"Text({_sw(w.props['text'])})"]
    if w.kind == "button": return [p + f"Button({_sw(w.props['label'])}) {{ /* handler: runtime Qich tertanam (PLANNED) */ }}"]
    if w.kind == "input": return [p + f"TextField({_sw(w.props['placeholder'])}, text: .constant({_sw(w.props['value'])}))"]
    out = [p + ("HStack {" if w.kind == "row" else "VStack(alignment: .leading) {")]
    for c in w.children: out += _swift(c, ind + 1)
    out.append(p + "}")
    return out


class App:
    __qh__ = {"view", "render", "render_text", "render_html", "save_html", "click", "type", "start", "stop",
              "on_start", "on_stop", "run", "to_kotlin", "to_swift", "title", "watch", "running"}

    def __init__(self, title="App"):
        self.title = to_str(title); self.view_fn = None; self.I = None
        self._start = []; self._stop = []; self.running = False; self._tk_redraw = None

    def view(self, fn): self.view_fn = fn
    def on_start(self, fn): self._start.append(fn)
    def on_stop(self, fn): self._stop.append(fn)

    def watch(self, state):
        state.subs.append(lambda: self._tk_redraw and self._tk_redraw())

    def start(self):
        if not self.running:
            self.running = True
            for f in self._start: self.I.call(f, [])

    def stop(self):
        if self.running:
            for f in self._stop: self.I.call(f, [])
            self.running = False

    def render(self):
        if self.view_fn is None: raise _err("App belum punya view(); panggil app.view(fn)")
        w = self.I.call(self.view_fn, [])
        if not isinstance(w, Widget): raise _err("view() harus mengembalikan Widget")
        return w

    def render_text(self): return "\n".join(_text(self.render()))

    def render_html(self):
        return ("<!doctype html><html><head><meta charset=\"utf-8\"><meta http-equiv=\"Content-Security-Policy\" "
                "content=\"default-src 'none'; style-src 'unsafe-inline'\"><title>" + _html_escape(self.title) +
                "</title></head><body>" + _to_html(self.render()) + "</body></html>")

    def save_html(self, path):
        try:
            with open(path, "w", encoding="utf-8") as f: f.write(self.render_html())
            return Ok(None)
        except OSError as e:
            return Err(make_error(str(e), "OSError"))

    def click(self, label):
        for w in _walk(self.render()):
            if w.kind == "button" and w.props["label"] == label:
                if w.props["on_click"] is not None: self.I.call(w.props["on_click"], [])
                return True
        return False

    def type(self, name, text):
        for w in _walk(self.render()):
            if w.kind == "input" and w.props["name"] == name:
                if w.props["on_change"] is not None: self.I.call(w.props["on_change"], [to_str(text)])
                return True
        return False

    def to_kotlin(self):
        lines = []; counter = [0]
        root = _kotlin(self.render(), "root", lines, counter)
        body = "\n".join(lines)
        return ("package app.qich\n\nimport android.app.Activity\nimport android.os.Bundle\nimport android.widget.*\n\n"
                "// Dihasilkan oleh qapp (UI statis). Belum dikompilasi di lingkungan pengembangan Qich.\n"
                f"class MainActivity : Activity() {{\n    override fun onCreate(savedInstanceState: Bundle?) {{\n"
                f"        super.onCreate(savedInstanceState)\n        title = {_kt(self.title)}\n{body}\n        setContentView({root})\n    }}\n}}\n")

    def to_swift(self):
        body = "\n".join(_swift(self.render(), 2))
        return ("import SwiftUI\n\n// Dihasilkan oleh qapp (UI statis). Belum dikompilasi di lingkungan pengembangan Qich.\n"
                f"struct ContentView: View {{\n    var body: some View {{\n{body}\n    }}\n}}\n\n"
                f"@main\nstruct {re.sub(r'[^A-Za-z0-9]', '', self.title) or 'QichApp'}App: App {{\n"
                "    var body: some Scene { WindowGroup { ContentView() } }\n}\n")

    def run(self, headless=False):
        self.start()
        if headless:
            return Ok(self.render_text())
        try:
            import tkinter as tk
        except ImportError:
            return Err(make_error("tkinter tidak tersedia; gunakan headless: true atau save_html()", "ImportError"))
        root = tk.Tk(); root.title(self.title)
        frame = tk.Frame(root); frame.pack(padx=12, pady=12)
        app = self

        def build(parent, w):
            if w.kind == "text": tk.Label(parent, text=w.props["text"]).pack(anchor="w")
            elif w.kind == "button":
                h = w.props["on_click"]
                tk.Button(parent, text=w.props["label"], command=lambda: (app.I.call(h, []) if h else None, redraw())).pack(anchor="w")
            elif w.kind == "input":
                v = tk.StringVar(value=w.props["value"]); h = w.props["on_change"]
                ent = tk.Entry(parent, textvariable=v); ent.pack(anchor="w")
                if h: v.trace_add("write", lambda *a: app.I.call(h, [v.get()]))
            else:
                f = tk.Frame(parent); f.pack(anchor="w")
                for c in w.children:
                    sub = tk.Frame(f); sub.pack(side="left" if w.kind == "row" else "top", anchor="w"); build(sub, c)

        def redraw():
            for ch in frame.winfo_children(): ch.destroy()
            build(frame, app.render())
        self._tk_redraw = redraw; redraw()
        root.protocol("WM_DELETE_WINDOW", lambda: (app.stop(), root.destroy()))
        root.mainloop()
        return Ok(None)


class Storage:
    """Penyimpanan key-value JSON per aplikasi, atomic write, key divalidasi."""
    __qh__ = {"get", "set", "delete", "keys", "path"}
    KEY = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")

    def __init__(self, app_name):
        if not re.match(r"^[A-Za-z0-9_-]{1,60}$", str(app_name)): raise _err("nama aplikasi tidak valid")
        base = os.environ.get("QH_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".local", "share", "qich")
        os.makedirs(os.path.join(base, app_name), exist_ok=True)
        self.path = os.path.join(base, app_name, "data.json")

    def _load(self):
        try:
            if os.path.getsize(self.path) > 10 * 1024 * 1024: raise _err("storage terlalu besar")
            with open(self.path, encoding="utf-8") as f: return json.load(f)
        except FileNotFoundError: return {}
        except ValueError: raise _err("storage rusak")

    def _save(self, d):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f: json.dump(d, f, allow_nan=False)
        os.replace(tmp, self.path)

    def _k(self, k):
        if type(k) is not str or not self.KEY.match(k): raise _err("key storage tidak valid (a-z A-Z 0-9 _ . -, maks 100)")
        return k

    def get(self, k, default=None): return self._load().get(self._k(k), default)

    def set(self, k, v):
        d = self._load(); d[self._k(k)] = json.loads(json.dumps(v, allow_nan=False)); self._save(d)

    def delete(self, k):
        d = self._load(); d.pop(self._k(k), None); self._save(d)

    def keys(self): return sorted(self._load())


def _ui(I):
    def make_app(title="App"):
        a = App(title); a.I = I; return a
    return {"App": make_app, "Text": Text, "Button": Button, "Input": Input, "Column": Column, "Row": Row, "State": State}


MODULES = {"ui": _ui, "storage": lambda I: {"Storage": Storage}}
