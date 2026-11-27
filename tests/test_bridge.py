import json
import os, shutil, subprocess, tempfile, unittest
from helpers import run, Policy, QichError


class Bridge(unittest.TestCase):
    def test_python(self):
        out = run('use py:math\nuse py:json\nuse py:collections\nprint(math.sqrt(49), json.dumps({a: [1, 2]}))\n'
                  'let d = collections.OrderedDict()\nd.update({x: 1})\nprint(d.get("x"))')
        self.assertEqual(out.split("\n")[0], '7.0 {"a": [1, 2]}')

    def test_python_callbacks_and_errors(self):
        self.assertEqual(run('use py:functools\nprint(functools.reduce(fn(a, b) rtrn => a * b, [1, 2, 3, 4]))').strip(), "24")
        out = run('use py:json\ntry { json.loads("{bad") } catch e { print(e.kind) }')
        self.assertEqual(out.strip(), "ForeignError")

    def test_python_missing_module_message(self):
        with self.assertRaises(QichError) as c: run("use py:modul_tidak_ada_xyz")
        self.assertIn("pip", c.exception.hint)

    @unittest.skipUnless(shutil.which("node"), "node tidak tersedia")
    def test_javascript(self):
        out = run('use js:path\nuse js:util\nprint(path.join("a", "b"), path.basename("/x/y.txt"))\n'
                  'print(util.format("%s-%d", "n", 5))\nlet p = path.parse("/a/b.txt")\nprint(p["name"])')
        self.assertEqual(out.split("\n"), ["a/b y.txt", "n-5", "b", ""])

    @unittest.skipUnless(shutil.which("node"), "node tidak tersedia")
    def test_javascript_bridge_preserves_proto_key_without_prototype_mutation(self):
        helper = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "src", "qich", "bridge", "js_helper.js"
        ))
        script = r"""
const { enc, dec, safeMemberName } = require(process.argv[1]);
const input = JSON.parse('{"__proto__":{"polluted":true},"safe":1}');
const encoded = enc(input);
if (Object.getPrototypeOf(encoded.v) !== null) process.exit(2);
if (!Object.prototype.hasOwnProperty.call(encoded.v, "__proto__")) process.exit(3);
const decoded = dec(encoded);
if (Object.getPrototypeOf(decoded) !== null) process.exit(4);
if (!Object.prototype.hasOwnProperty.call(decoded, "__proto__")) process.exit(5);
if (Object.prototype.polluted !== undefined) process.exit(6);
if (safeMemberName("__proto__")) process.exit(7);
if (safeMemberName("x".repeat(257))) process.exit(8);
"""
        subprocess.check_call(["node", "-e", script, helper])

    @unittest.skipUnless(shutil.which("node"), "node tidak tersedia")
    def test_javascript_policy_normalizes_node_builtin_subpaths(self):
        for mod in ("fs/promises", "node:fs/promises", "inspector/promises",
                    "node:module", "node:process", "dgram", "dns", "tls", "wasi"):
            with self.subTest(module=mod):
                self.assertFalse(Policy().check_bridge("js", mod))
        self.assertTrue(Policy(allow=["js:fs/promises"]).check_bridge("js", "fs/promises"))

    @unittest.skipUnless(shutil.which("node"), "node tidak tersedia")
    def test_javascript_protocol_recovers_after_malformed_requests(self):
        helper = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "src", "qich", "bridge", "js_helper.js"
        ))
        valid = json.dumps({"rid": 7, "op": "import", "lib": "path"})
        proc = subprocess.run(
            ["node", helper],
            input='null\n{"rid":1\n' + valid + '\n',
            capture_output=True, text=True, timeout=10
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        responses = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(len(responses), 3)
        self.assertFalse(responses[0]["ok"])
        self.assertFalse(responses[1]["ok"])
        self.assertEqual(responses[2]["rid"], 7)
        self.assertTrue(responses[2]["ok"])

    @unittest.skipUnless(shutil.which("node"), "node tidak tersedia")
    def test_javascript_protocol_bounds_request_size_and_continues(self):
        helper = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "src", "qich", "bridge", "js_helper.js"
        ))
        valid = json.dumps({"rid": 8, "op": "import", "lib": "path"})
        oversized = "x" * (1024 * 1024 + 1)
        proc = subprocess.run(
            ["node", helper],
            input=oversized + "\n" + valid + "\n",
            capture_output=True, text=True, timeout=15
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        responses = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertFalse(responses[0]["ok"])
        self.assertEqual(responses[1]["rid"], 8)
        self.assertTrue(responses[1]["ok"])

    @unittest.skipUnless(shutil.which("node"), "node tidak tersedia")
    def test_javascript_handle_table_and_cyclic_values_are_bounded(self):
        helper = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "src", "qich", "bridge", "js_helper.js"
        ))
        script = r"""
const { enc, MAX_HANDLES } = require(process.argv[1]);
const cycle = []; cycle.push(cycle);
if (typeof JSON.stringify(enc(cycle)) !== "string") process.exit(2);
for (let i = 0; i < MAX_HANDLES - 1; i++) enc(() => {});
try {
  enc(() => {});
  process.exit(3);
} catch (e) {
  if (!String(e.message).includes("batas handle")) process.exit(4);
}
"""
        subprocess.check_call(["node", "-e", script, helper])

    @unittest.skipUnless(shutil.which("node"), "node tidak tersedia")
    def test_javascript_errors_and_isolation(self):
        # Bridge Node bukan sandbox OS. Modul sensitif diblokir pada jalur import,
        # tetapi kode pihak ketiga yang dijalankan Node tetap tidak terisolasi OS.
        for mod in ("fs", "node:fs", "fs/promises", "node:fs/promises",
                    "http", "https", "net", "module", "os", "worker_threads",
                    "child_process", "vm", "process", "node:process"):
            with self.assertRaises(QichError, msg=mod):
                run(f"use js:{mod}")

    def test_c(self):
        out = run('use c:m\nuse c:c\nlet cos = m.fn("cos", ["f64"], "f64")\nlet strlen = c.fn("strlen", ["str"], "usize")\nprint(cos(0.0), strlen("héllo"))')
        self.assertEqual(out.split(), ["1.0", "6"])

    @unittest.skipUnless(shutil.which("g++"), "g++ tidak tersedia")
    def test_cpp_extern_c(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "m.cpp"); so = os.path.join(d, "libm2.so")
            open(src, "w").write('#include <string>\nextern "C" { int tambah(int a, int b) { return a + b; }\n'
                                 'const char* sapa() { static std::string s = std::string("halo dari c++"); return s.c_str(); } }\n')
            subprocess.check_call(["g++", "-shared", "-fPIC", "-o", so, src])
            out = run(f'use c:ffi\nlet lib = ffi.open("{so}")\nlet t = lib.fn("tambah", ["i32", "i32"], "i32")\n'
                      f'let s = lib.fn("sapa", [], "str")\nprint(t(2, 3), s())', Policy(allow=["c:ffi"]))
            self.assertEqual(out.strip(), "5 halo dari c++")
            with self.assertRaises(QichError): run(f'use c:ffi\nlet lib = ffi.open("{so}")\nlib.fn("tambah", ["i32", "i32"], "i32")(2**40, 1)', Policy(allow=["c:ffi"]))

    def test_planned_adapters_honest(self):
        for eco in ("go", "rust", "java", "dart", "swift", "php", "rb", "cs", "ts"):
            with self.assertRaises(QichError) as c: run(f"use {eco}:lib")
            self.assertIn("PLANNED", c.exception.msg)
        with self.assertRaises(QichError) as c: run("use zzz:lib")
        self.assertIn("tidak dikenal", c.exception.msg)

    def test_capability_table(self):
        from qich.bridge import capabilities_table
        t = {k: s for k, _, s, _ in capabilities_table()}
        self.assertEqual(t["py"], "TESTED"); self.assertEqual(t["go"], "PLANNED")
        self.assertGreaterEqual(len(t), 30)


if __name__ == "__main__":
    unittest.main()
