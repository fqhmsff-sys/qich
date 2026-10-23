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
    def test_javascript_errors_and_isolation(self):
        out = run('use js:fs\ntry { fs.readFileSync("/tidak/ada") } catch e { print(e.kind) }', Policy())
        self.assertEqual(out.strip(), "ForeignError")
        with self.assertRaises(QichError): run("use js:child_process")
        with self.assertRaises(QichError): run("use js:vm")
        # Proses terpisah bukan sandbox: modul dengan filesystem/network/process
        # harus fail-closed kecuali kelak ada capability grant eksplisit.
        for mod in ("fs", "http", "https", "net", "module", "os", "worker_threads"):
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
