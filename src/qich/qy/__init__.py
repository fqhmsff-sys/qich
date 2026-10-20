"""qy: AI. Tensor, model feed-forward terlatih (backprop+SGD), data pipeline, dan LM n-gram.

Backend: 'python' (murni, TESTED). Backend lain (numpy/torch/C++) PLANNED; API tidak berubah saat backend ditambah.
Model dimuat dari JSON ter-skema (BUKAN pickle) dengan validasi ketat: model tak tepercaya tidak bisa menjalankan kode.
"""
import json
import math
import os
import random
from ..compiler.diagnostics import QichError
from ..runtime.values import Ok, Err, make_error

MAX_PARAMS = 5_000_000
MAX_FILE = 100 * 1024 * 1024
ACTS = {"linear", "relu", "sigmoid", "tanh", "softmax"}


def _err(msg, kind="ValueError"):
    return QichError(msg, kind, "R0400")


def backends():
    return [{"name": "python", "status": "TESTED", "available": True},
            {"name": "numpy", "status": "PLANNED", "available": False},
            {"name": "torch (via py:)", "status": "PLANNED", "available": False},
            {"name": "cpp-engine", "status": "PLANNED", "available": False}]


def _is_num(x): return type(x) in (int, float)


class Tensor:
    __qh__ = {"shape", "tolist", "add", "sub", "mul", "scale", "matmul", "transpose", "relu", "sigmoid",
              "tanh", "softmax", "sum", "mean", "argmax", "reshape", "zeros", "rand", "len"}

    def __init__(self, data, shape=None):
        if shape is None:
            data, shape = self._flatten(data)
        n = 1
        for s in shape: n *= s
        if n != len(data): raise _err("bentuk tensor tidak cocok dengan jumlah data")
        if n > 50_000_000: raise _err("tensor terlalu besar", "ResourceLimit")
        self.data = data; self.shp = tuple(shape)

    @staticmethod
    def _flatten(x):
        if _is_num(x): return [float(x)], ()
        if type(x) is not list or not x: raise _err("tensor butuh list angka bersarang (tidak kosong)")
        subs = [Tensor._flatten(i) for i in x]
        sh = subs[0][1]
        if any(s[1] != sh for s in subs): raise _err("list bersarang tidak berbentuk persegi")
        flat = []
        for s in subs: flat.extend(s[0])
        return flat, (len(x),) + sh

    @staticmethod
    def zeros(shape):
        n = 1
        for s in shape: n *= s
        return Tensor([0.0] * n, list(shape))

    @staticmethod
    def rand(shape, seed=0):
        r = random.Random(seed); n = 1
        for s in shape: n *= s
        return Tensor([r.random() for _ in range(n)], list(shape))

    def shape(self): return list(self.shp)
    def len(self): return len(self.data)

    def tolist(self):
        def build(off, dims):
            if not dims: return self.data[off]
            step = 1
            for d in dims[1:]: step *= d
            return [build(off + i * step, dims[1:]) for i in range(dims[0])]
        return build(0, list(self.shp))

    def _same(self, o):
        if not isinstance(o, Tensor) or o.shp != self.shp: raise _err("bentuk tensor harus sama")

    def add(self, o): self._same(o); return Tensor([a + b for a, b in zip(self.data, o.data)], self.shp)
    def sub(self, o): self._same(o); return Tensor([a - b for a, b in zip(self.data, o.data)], self.shp)
    def mul(self, o): self._same(o); return Tensor([a * b for a, b in zip(self.data, o.data)], self.shp)
    def scale(self, k): return Tensor([a * k for a in self.data], self.shp)
    def relu(self): return Tensor([a if a > 0 else 0.0 for a in self.data], self.shp)
    def sigmoid(self): return Tensor([_sig(a) for a in self.data], self.shp)
    def tanh(self): return Tensor([math.tanh(a) for a in self.data], self.shp)
    def sum(self): return sum(self.data)
    def mean(self): return sum(self.data) / len(self.data)
    def argmax(self): return max(range(len(self.data)), key=lambda i: self.data[i])

    def softmax(self):
        if len(self.shp) != 1: raise _err("softmax butuh tensor 1D")
        return Tensor(_softmax(self.data), self.shp)

    def reshape(self, shape): return Tensor(list(self.data), list(shape))

    def transpose(self):
        if len(self.shp) != 2: raise _err("transpose butuh tensor 2D")
        r, c = self.shp
        return Tensor([self.data[i * c + j] for j in range(c) for i in range(r)], (c, r))

    def matmul(self, o):
        if not isinstance(o, Tensor) or len(self.shp) != 2 or len(o.shp) != 2 or self.shp[1] != o.shp[0]:
            raise _err("matmul butuh dua tensor 2D dengan dimensi dalam cocok")
        n, k = self.shp; m = o.shp[1]; out = [0.0] * (n * m)
        for i in range(n):
            for p in range(k):
                a = self.data[i * k + p]
                if a == 0.0: continue
                row = p * m
                for j in range(m): out[i * m + j] += a * o.data[row + j]
        return Tensor(out, (n, m))

    def __qh_repr__(self): return f"Tensor(shape={list(self.shp)})"


def _sig(x):
    if x >= 0: return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x); return e / (1.0 + e)


def _softmax(v):
    m = max(v); ex = [math.exp(a - m) for a in v]; s = sum(ex)
    return [e / s for e in ex]


def _act(name, z):
    if name == "linear": return list(z)
    if name == "relu": return [a if a > 0 else 0.0 for a in z]
    if name == "sigmoid": return [_sig(a) for a in z]
    if name == "tanh": return [math.tanh(a) for a in z]
    return _softmax(z)


def _dact(name, out):  # turunan terhadap pre-aktivasi, dihitung dari output
    if name == "linear": return [1.0] * len(out)
    if name == "relu": return [1.0 if a > 0 else 0.0 for a in out]
    if name == "sigmoid": return [a * (1 - a) for a in out]
    if name == "tanh": return [1 - a * a for a in out]
    return [1.0] * len(out)  # softmax: gunakan bersama loss langsung


class Dense:
    __qh__ = {"n_in", "n_out", "act"}

    def __init__(self, n_in, n_out, act="relu", w=None, b=None, seed=None):
        if type(n_in) is not int or type(n_out) is not int or n_in < 1 or n_out < 1:
            raise _err("Dense(n_in, n_out, act): n_in/n_out harus int positif")
        if act not in ACTS: raise _err(f"aktivasi tidak dikenal '{act}'; tersedia: {', '.join(sorted(ACTS))}")
        if n_in * n_out > MAX_PARAMS: raise _err("layer terlalu besar", "ResourceLimit")
        self.n_in = n_in; self.n_out = n_out; self.act = act
        if w is None:
            r = random.Random(seed); lim = math.sqrt(6.0 / (n_in + n_out))
            w = [[r.uniform(-lim, lim) for _ in range(n_in)] for _ in range(n_out)]
            b = [0.0] * n_out
        self.w = w; self.b = b

    def forward(self, x):
        z = [sum(wi * xi for wi, xi in zip(row, x)) + bi for row, bi in zip(self.w, self.b)]
        return _act(self.act, z)


class Model:
    __qh__ = {"sequential", "load", "fit", "predict", "run", "save", "n_params", "backend"}

    def __init__(self, layers, backend="python"):
        self.layers = layers; self.backend = backend

    @staticmethod
    def sequential(layers, seed=0):
        if type(layers) is not list or not layers or not all(isinstance(l, Dense) for l in layers):
            raise _err("Model.sequential butuh list Dense tidak kosong")
        for a, b in zip(layers, layers[1:]):
            if a.n_out != b.n_in: raise _err(f"dimensi layer tidak cocok: {a.n_out} -> {b.n_in}")
        r = random.Random(seed)
        for l in layers:
            lim = math.sqrt(6.0 / (l.n_in + l.n_out))
            l.w = [[r.uniform(-lim, lim) for _ in range(l.n_in)] for _ in range(l.n_out)]
        return Model(layers)

    def n_params(self): return sum(l.n_in * l.n_out + l.n_out for l in self.layers)

    def _x(self, x):
        if type(x) is Tensor: x = x.data
        if type(x) is not list or len(x) != self.layers[0].n_in or not all(_is_num(i) for i in x):
            raise _err(f"input harus list {self.layers[0].n_in} angka")
        return [float(i) for i in x]

    def predict(self, x):
        a = self._x(x)
        for l in self.layers: a = l.forward(a)
        return a

    def run(self, x):
        try:
            return Ok(self.predict(x))
        except QichError as e:
            return Err(make_error(e.msg, e.kind))

    def fit(self, xs, ys, epochs=1000, lr=0.1, seed=0):
        if type(xs) is not list or type(ys) is not list or len(xs) != len(ys) or not xs:
            raise _err("fit(xs, ys): dua list sama panjang, tidak kosong")
        if type(epochs) is not int or epochs < 1 or epochs > 10_000_000: raise _err("epochs tidak valid")
        data = [(self._x(x), [float(v) for v in (y if type(y) is list else [y])]) for x, y in zip(xs, ys)]
        if any(len(y) != self.layers[-1].n_out for _, y in data): raise _err("dimensi target tidak cocok dengan output model")
        rnd = random.Random(seed); loss = 0.0
        for _ in range(epochs):
            rnd.shuffle(data); loss = 0.0
            for x, t in data:
                acts = [x]
                for l in self.layers: acts.append(l.forward(acts[-1]))
                out = acts[-1]
                loss += sum((o - ti) ** 2 for o, ti in zip(out, t)) / len(t)
                last = self.layers[-1]
                if last.act == "softmax":
                    delta = [o - ti for o, ti in zip(out, t)]
                else:
                    delta = [(o - ti) * d for o, ti, d in zip(out, t, _dact(last.act, out))]
                for li in range(len(self.layers) - 1, -1, -1):
                    l = self.layers[li]; a_in = acts[li]
                    if li > 0:
                        prev = self.layers[li - 1]
                        back = [sum(l.w[j][i] * delta[j] for j in range(l.n_out)) for i in range(l.n_in)]
                        nd = [bk * d for bk, d in zip(back, _dact(prev.act, acts[li]))]
                    for j in range(l.n_out):
                        dj = delta[j] * lr
                        row = l.w[j]
                        for i in range(l.n_in): row[i] -= dj * a_in[i]
                        l.b[j] -= dj
                    if li > 0: delta = nd
            loss /= len(data)
        return loss

    def save(self, path):
        try:
            doc = {"format": "qy-model", "version": 1,
                   "layers": [{"in": l.n_in, "out": l.n_out, "act": l.act, "w": l.w, "b": l.b} for l in self.layers]}
            tmp = path + ".tmp"
            with open(tmp, "w") as f: json.dump(doc, f, allow_nan=False)
            os.replace(tmp, path)
            return Ok(None)
        except (OSError, ValueError) as e:
            return Err(make_error(str(e), type(e).__name__))

    @staticmethod
    def load(path, backend="auto"):
        try:
            if os.path.getsize(path) > MAX_FILE: return Err(make_error("file model terlalu besar", "ResourceLimit"))
            with open(path, encoding="utf-8") as f:
                doc = json.load(f, parse_constant=lambda c: (_ for _ in ()).throw(ValueError("konstanta non-finite")))
            return Ok(Model._from_doc(doc))
        except (OSError, ValueError, RecursionError) as e:
            return Err(make_error(f"model tidak valid: {e}", "ModelError"))
        except QichError as e:
            return Err(make_error(f"model tidak valid: {e.msg}", "ModelError"))

    @staticmethod
    def _from_doc(doc):
        if not isinstance(doc, dict) or doc.get("format") != "qy-model" or doc.get("version") != 1:
            raise ValueError("format/versi tidak dikenal")
        ls = doc.get("layers")
        if not isinstance(ls, list) or not ls or len(ls) > 1000: raise ValueError("layers tidak valid")
        total = 0; layers = []
        for i, d in enumerate(ls):
            if not isinstance(d, dict): raise ValueError("layer tidak valid")
            n_in, n_out, act, w, b = d.get("in"), d.get("out"), d.get("act"), d.get("w"), d.get("b")
            if type(n_in) is not int or type(n_out) is not int or n_in < 1 or n_out < 1: raise ValueError("dimensi layer tidak valid")
            if act not in ACTS: raise ValueError("aktivasi tidak dikenal")
            total += n_in * n_out + n_out
            if total > MAX_PARAMS: raise ValueError("model melebihi batas parameter")
            if not (isinstance(w, list) and len(w) == n_out and all(isinstance(r, list) and len(r) == n_in for r in w)): raise ValueError("bobot tidak sesuai dimensi")
            if not (isinstance(b, list) and len(b) == n_out): raise ValueError("bias tidak sesuai dimensi")
            if not all(_is_num(v) and math.isfinite(v) for r in w for v in r) or not all(_is_num(v) and math.isfinite(v) for v in b):
                raise ValueError("bobot harus angka finite")
            if layers and layers[-1].n_out != n_in: raise ValueError("dimensi antar layer tidak cocok")
            layers.append(Dense(n_in, n_out, act, [[float(v) for v in r] for r in w], [float(v) for v in b]))
        return Model(layers)

    def __qh_repr__(self): return f"Model({len(self.layers)} layer, {self.n_params()} param)"


# ------------------------------------------------------------ LM n-gram (EXPERIMENTAL)
class NgramLM:
    """Model bahasa karakter n-gram dengan backoff. Fondasi LLM Qich tahap awal (BUKAN transformer; itu PLANNED)."""
    __qh__ = {"train", "generate", "save", "load", "order", "vocab_size"}

    def __init__(self, order=3, counts=None):
        self.order = order; self.counts = counts or {}

    @staticmethod
    def train(text, order=3):
        if type(text) is not str or not text: raise _err("train(text, order): text harus str tidak kosong")
        if type(order) is not int or not 1 <= order <= 8: raise _err("order harus 1..8")
        if len(text) > 20_000_000: raise _err("teks terlalu besar", "ResourceLimit")
        counts = {}
        for i in range(len(text)):
            for k in range(0, order):
                if i - k < 0: break
                ctx = text[i - k:i]
                d = counts.setdefault(ctx, {})
                d[text[i]] = d.get(text[i], 0) + 1
        return NgramLM(order, counts)

    def vocab_size(self): return len(self.counts.get("", {}))

    def generate(self, prompt="", n=100, seed=0, temperature=1.0):
        if type(n) is not int or not 0 <= n <= 100_000: raise _err("n harus 0..100000")
        if not temperature > 0: raise _err("temperature harus > 0")
        r = random.Random(seed); out = prompt
        for _ in range(n):
            nxt = None
            for k in range(self.order - 1, -1, -1):
                ctx = out[len(out) - k:] if k else ""
                if k > len(out): continue
                d = self.counts.get(ctx)
                if d:
                    chars = list(d); ws = [c ** (1.0 / temperature) for c in d.values()]
                    nxt = r.choices(chars, ws)[0]; break
            if nxt is None: break
            out += nxt
        return out

    def save(self, path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"format": "qy-ngram", "version": 1, "order": self.order, "counts": self.counts}, f)
            return Ok(None)
        except OSError as e:
            return Err(make_error(str(e), "OSError"))

    @staticmethod
    def load(path):
        try:
            if os.path.getsize(path) > MAX_FILE: raise ValueError("file terlalu besar")
            with open(path, encoding="utf-8") as f: doc = json.load(f)
            if not isinstance(doc, dict) or doc.get("format") != "qy-ngram" or doc.get("version") != 1: raise ValueError("format tidak dikenal")
            o, c = doc.get("order"), doc.get("counts")
            if type(o) is not int or not 1 <= o <= 8 or not isinstance(c, dict): raise ValueError("isi tidak valid")
            for k, d in c.items():
                if not isinstance(d, dict) or len(k) >= o or not all(type(v) is int and v > 0 for v in d.values()): raise ValueError("counts tidak valid")
            return Ok(NgramLM(o, c))
        except (OSError, ValueError, RecursionError) as e:
            return Err(make_error(f"model tidak valid: {e}", "ModelError"))


# ------------------------------------------------------------ data
def shuffle(xs, seed=0):
    out = list(xs); random.Random(seed).shuffle(out); return out


def batches(xs, size):
    if type(size) is not int or size < 1: raise _err("ukuran batch harus int positif")
    return [xs[i:i + size] for i in range(0, len(xs), size)]


def split(xs, ratio=0.8):
    if not 0 < ratio < 1: raise _err("ratio harus di antara 0 dan 1")
    k = int(len(xs) * ratio); return [xs[:k], xs[k:]]


def normalize(xs):
    if not xs: return []
    lo, hi = min(xs), max(xs)
    return [0.0 for _ in xs] if hi == lo else [(x - lo) / (hi - lo) for x in xs]


MODULES = {
    "tensor": lambda I: {"Tensor": Tensor},
    "model": lambda I: {"Model": Model, "Dense": Dense, "Tensor": Tensor, "backends": backends},
    "lm": lambda I: {"NgramLM": NgramLM},
    "data": lambda I: {"shuffle": shuffle, "batches": batches, "split": split, "normalize": normalize},
}
