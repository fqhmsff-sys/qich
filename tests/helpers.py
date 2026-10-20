import io, os, sys, subprocess, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from qich.compiler import parse
from qich.compiler.diagnostics import QichError
from qich.runtime.interp import Interp
from qich.security import Policy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def run(src, policy=None, **kw):
    out = io.StringIO()
    I = Interp(out=out, policy=policy or Policy(), **kw)
    I.run_module(parse(src, "t.qh"), "t.qh")
    return out.getvalue()


def qh(args, cwd, env=None, check=False):
    e = dict(os.environ); e["PYTHONPATH"] = os.path.join(ROOT, "src"); e.update(env or {})
    p = subprocess.run([sys.executable, "-m", "qich"] + args, cwd=cwd, capture_output=True, text=True, env=e, timeout=300)
    return p
