import io, json, os, random, sys, tempfile, unittest, zipfile, hashlib
from helpers import run, parse, QichError, Policy, ROOT
from qich.security import safe_extract_zip
from qich.compiler import qhc
from qich.runtime.interp import Interp
from qich.compiler.diagnostics import QichError as QE


class Security(unittest.TestCase):
    def test_zip_slip_and_symlink_and_bomb(self):
        def z(name, data=b"x", attr=None):
            b = io.BytesIO()
            with zipfile.ZipFile(b, "w") as f:
                zi = zipfile.ZipInfo(name)
                if attr: zi.external_attr = attr << 16
                f.writestr(zi, data)
            return b.getvalue()
        with tempfile.TemporaryDirectory() as d:
            for bad in (z("../evil"), z("/abs"), z("l", b"/etc/passwd", 0o120777)):
                with self.assertRaises(ValueError): safe_extract_zip(bad, d)
            with self.assertRaises(ValueError): safe_extract_zip(z("big", b"0" * 5000), d, max_total=100)
            safe_extract_zip(z("ok/a.txt"), d); self.assertTrue(os.path.isfile(os.path.join(d, "ok", "a.txt")))

    def test_bridge_denylist_and_allow(self):
        with self.assertRaises(QE) as c: run("use py:os")
        self.assertEqual(c.exception.kind, "SecurityError")
        with self.assertRaises(QE): run("use js:child_process")
        run("use py:os\nprint(os.getcwd() != nil)", Policy(allow=["py:os"]))

    def test_private_attr_blocked(self):
        with self.assertRaises(QE): run("use py:json\nprint(json.__dict__)")

    def test_secret_never_printed_or_bridged_or_serialized(self):
        os.environ["QH_TEST_SECRET"] = "hunter2"
        out = run('use std:os\nlet s = os.secret("QH_TEST_SECRET")\nprint(s)\nprint(f"{s}")')
        self.assertNotIn("hunter2", out); self.assertIn("***", out)
        with self.assertRaises(QE): run('use std:os\nuse py:json\nlet s = os.secret("QH_TEST_SECRET")\njson.dumps(s)')
        out = run('use std:os\nuse std:json\nlet s = os.secret("QH_TEST_SECRET")\nprint(json.stringify(s).is_err())')
        self.assertEqual(out.strip(), "true")

    def test_process_spawn_no_shell_and_secret_env_stripped(self):
        os.environ["QH_API_TOKEN"] = "tok123"
        out = run('use std:os\nlet r = os.run(["env"]).unwrap()\nprint(r["out"].contains("tok123"))')
        self.assertEqual(out.strip(), "false")
        out = run('use std:os\nprint(os.run("echo hi; id").is_err())')
        self.assertEqual(out.strip(), "true")
        out = run('use std:os\nprint(os.run(["echo", "a; id"]).unwrap()["out"].trim())')
        self.assertEqual(out.strip(), "a; id")

    def test_http_client_defaults(self):
        out = run('use std:http\nprint(http.get("http://example.com").err().msg.contains("TLS"))\nprint(http.get("file:///etc/passwd").is_err())')
        self.assertEqual(out.split(), ["true", "true"])

    def test_resource_limits(self):
        with self.assertRaises(QE) as c: run("whl true { }", max_steps=10000)
        self.assertEqual(c.exception.kind, "ResourceLimit")
        with self.assertRaises(QE) as c: run('let s = "a" * 100000000000')
        self.assertEqual(c.exception.kind, "ResourceLimit")
        with self.assertRaises(QE): run("fn f(n) rtrn => f(n + 1)\nf(0)")

    def test_parser_nesting_limit(self):
        with self.assertRaises(QE): parse("let x = " + "(" * 5000 + "1" + ")" * 5000, "a.qh")
        with self.assertRaises(QE): parse("let x = " + "[" * 5000 + "]" * 5000, "a.qh")

    def test_fuzz_parser_and_runtime_never_crash(self):
        base = open(os.path.join(ROOT, "tests", "qh", "language_test.qh"), encoding="utf-8").read()
        rnd = random.Random(1337); toks = ["{", "}", "(", ")", "[", "]", '"', "fn", "let", "mtch", "=>", "..", "?", ":", "\\", "0x", "f\"{", "/*", "//"]
        for i in range(400):
            s = list(base[rnd.randrange(len(base) - 600):][:600])
            for _ in range(rnd.randrange(1, 12)):
                p = rnd.randrange(len(s) + 1)
                r = rnd.random()
                if r < 0.4: s.insert(p, rnd.choice(toks))
                elif r < 0.7 and s: del s[min(p, len(s) - 1)]
                else: s.insert(p, chr(rnd.randrange(1, 0x2fff)))
            src = "".join(s)
            try:
                prog = parse(src, "f.qh")
                out = io.StringIO(); I = Interp(out=out, max_steps=20000, policy=Policy())
                try: I.run_module(prog, "f.qh")
                except QE: pass
                except BaseException as e:
                    if type(e).__name__ in ("QichThrow", "ReturnSig", "BreakSig", "ContinueSig"): pass
                    elif isinstance(e, SystemExit): pass
                    else: raise
            except QE: pass

    def test_untrusted_model_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            def tryload(doc, raw=False):
                p = os.path.join(d, "m.json")
                open(p, "w").write(doc if raw else json.dumps(doc))
                return run(f'use qy:model\nprint(Model.load("{p}").is_err())').strip()
            good = {"format": "qy-model", "version": 1, "layers": [{"in": 1, "out": 1, "act": "linear", "w": [[1.0]], "b": [0.0]}]}
            self.assertEqual(tryload(good), "false")
            self.assertEqual(tryload({"format": "pickle"}), "true")
            self.assertEqual(tryload('{"format":"qy-model","version":1,"layers":[{"in":1,"out":1,"act":"linear","w":[[NaN]],"b":[0]}]}', True), "true")
            self.assertEqual(tryload({"format": "qy-model", "version": 1, "layers": [{"in": 10**9, "out": 10**9, "act": "linear", "w": [], "b": []}]}), "true")
            self.assertEqual(tryload({"format": "qy-model", "version": 1, "layers": [{"in": 1, "out": 1, "act": "__import__('os')", "w": [[1]], "b": [0]}]}), "true")
            self.assertEqual(tryload("\x80\x04pickle bytes", True), "true")

    def test_qhc_rejects_malformed_structures(self):
        def artifact(payload):
            body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
            return qhc.MAGIC + hashlib.sha256(body).hexdigest().encode() + b"\\n" + body

        bad_payloads = [
            [],
            {"version": 1, "entry": "main", "modules": []},
            {"version": 1, "entry": [], "modules": {}},
            {"version": 1, "entry": "main", "modules": {"main": None}},
            {"version": 1, "entry": "main", "modules": {"main": {"file": "main.qh"}}},
            {"version": 1, "entry": "main", "meta": [], "modules": {}},
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    qhc.load(artifact(payload))

    def test_c_bridge_type_safety(self):
        with self.assertRaises(QE): run('use c:c\nlet f = c.fn("strlen", ["ptr"], "usize")')
        with self.assertRaises(QE): run('use c:c\nlet f = c.fn("strlen", ["str"], "usize")\nf(123)')
        with self.assertRaises(QE): run('use c:ffi\nffi.open("/tmp/x.so")')


if __name__ == "__main__":
    unittest.main()
