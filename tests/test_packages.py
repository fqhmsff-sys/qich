import json, os, shutil, tempfile, unittest
from helpers import qh, ROOT
from qich.package import registry
from qich.compiler.diagnostics import QichError


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(text)


def mkpkg(d, name, version, lib_body, deps=""):
    w(os.path.join(d, "qh.toml"), f'[package]\nname = "{name}"\nversion = "{version}"\n\n[dependencies]\n{deps}')
    w(os.path.join(d, "src", "lib.qh"), lib_body)


class Packages(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(); self.reg = os.path.join(self.t, "reg")
        self.env = {"QH_REGISTRY": self.reg}

    def tearDown(self): shutil.rmtree(self.t, ignore_errors=True)

    def proj(self):
        p = qh(["new", "app"], self.t); self.assertEqual(p.returncode, 0, p.stderr)
        return os.path.join(self.t, "app")

    def test_path_dependency_end_to_end(self):
        lib = os.path.join(self.t, "mylib"); mkpkg(lib, "mylib", "1.0.0", 'fn dobel(x) rtrn => x * 2\n')
        app = self.proj()
        p = qh(["add", "--path", "../mylib", "mylib"], app); self.assertEqual(p.returncode, 0, p.stderr)
        w(os.path.join(app, "src", "main.qh"), 'use pkg:mylib\nfn main() { print(mylib.dobel(21)) }\n')
        p = qh(["run"], app); self.assertEqual(p.stdout.strip(), "42", p.stderr)
        self.assertIn("sha256", open(os.path.join(app, "qh.lock")).read())
        p = qh(["build"], app); self.assertEqual(p.returncode, 0, p.stderr)
        shutil.rmtree(os.path.join(app, ".qh")); shutil.rmtree(lib)  # .qhc mandiri, tanpa dependensi
        p = qh(["run", "build/app.qhc"], app); self.assertEqual(p.stdout.strip(), "42", p.stderr)

    def test_integrity_failure_when_source_tampered(self):
        lib = os.path.join(self.t, "mylib"); mkpkg(lib, "mylib", "1.0.0", 'fn f() rtrn => 1\n')
        app = self.proj(); qh(["add", "--path", "../mylib", "mylib"], app)
        w(os.path.join(app, "src", "main.qh"), 'use pkg:mylib\nfn main() { print(mylib.f()) }\n')
        w(os.path.join(lib, "src", "lib.qh"), 'fn f() rtrn => 666  // disusupi\n')
        p = qh(["run"], app)
        self.assertNotEqual(p.returncode, 0); self.assertIn("integritas", p.stderr)
        self.assertEqual(qh(["update"], app).returncode, 0)  # perubahan sadar via update
        self.assertEqual(qh(["run"], app).stdout.strip(), "666")

    def test_registry_publish_add_audit_and_lock_pin(self):
        lib = os.path.join(self.t, "greet"); mkpkg(lib, "greet", "1.0.0", 'fn hi() rtrn => "v1"\n')
        self.assertEqual(qh(["publish", self.reg], lib).returncode, 0)
        p = qh(["publish", self.reg], lib); self.assertNotEqual(p.returncode, 0); self.assertIn("immutable", p.stderr)
        mkpkg(lib, "greet", "1.1.0", 'fn hi() rtrn => "v1.1"\n'); self.assertEqual(qh(["publish", self.reg], lib).returncode, 0)
        app = self.proj(); p = qh(["add", "greet"], app, self.env); self.assertEqual(p.returncode, 0, p.stderr)
        w(os.path.join(app, "src", "main.qh"), 'use pkg:greet\nfn main() { print(greet.hi()) }\n')
        self.assertEqual(qh(["run"], app, self.env).stdout.strip(), "v1.1")
        idx = json.load(open(os.path.join(self.reg, "index.json")))
        idx["advisories"] = {"greet": [{"id": "QH-2026-0001", "summary": "contoh", "affected": ["<1.2.0"]}]}
        json.dump(idx, open(os.path.join(self.reg, "index.json"), "w"))
        p = qh(["audit"], app, self.env); self.assertNotEqual(p.returncode, 0); self.assertIn("QH-2026-0001", p.stdout)

    def test_registry_archive_tamper_detected(self):
        lib = os.path.join(self.t, "greet"); mkpkg(lib, "greet", "1.0.0", 'fn hi() rtrn => "v1"\n')
        qh(["publish", self.reg], lib)
        with open(os.path.join(self.reg, "greet-1.0.0.qhpkg"), "ab") as f: f.write(b"X")
        app = self.proj(); p = qh(["add", "greet"], app, self.env)
        self.assertNotEqual(p.returncode, 0); self.assertIn("checksum", p.stderr)

    def test_typosquat_and_reserved_names(self):
        for n in ("requests", "reqeusts"):
            lib = os.path.join(self.t, n); mkpkg(lib, n, "1.0.0", 'fn f() rtrn => 1\n')
        # publikasi nama mirip yang sudah ada ditolak
        self.assertEqual(qh(["publish", self.reg], os.path.join(self.t, "requests")).returncode, 0)
        p = qh(["publish", self.reg], os.path.join(self.t, "reqeusts")); self.assertNotEqual(p.returncode, 0); self.assertIn("mirip", p.stderr)
        lib = os.path.join(self.t, "qy2"); mkpkg(lib, "qy", "1.0.0", 'fn f() rtrn => 1\n')
        self.assertNotEqual(qh(["publish", self.reg], lib).returncode, 0)
        app = self.proj(); p = qh(["add", "requestz"], app, self.env); self.assertNotEqual(p.returncode, 0)
        self.assertIn("requests", p.stderr)

    def test_dependency_confusion_source_change_blocked(self):
        lib = os.path.join(self.t, "internal"); mkpkg(lib, "internal", "1.0.0", 'fn f() rtrn => "privat"\n')
        app = self.proj(); qh(["add", "--path", "../internal", "internal"], app)
        evil = os.path.join(self.t, "evil"); mkpkg(evil, "internal", "9.9.9", 'fn f() rtrn => "jahat"\n'); qh(["publish", self.reg], evil)
        toml = open(os.path.join(app, "qh.toml")).read().replace('internal = { path = "../internal" }', 'internal = "9.9.9"')
        open(os.path.join(app, "qh.toml"), "w").write(toml)
        w(os.path.join(app, "src", "main.qh"), 'use pkg:internal\nfn main() { print(internal.f()) }\n')
        p = qh(["run"], app, self.env); self.assertNotEqual(p.returncode, 0); self.assertIn("dependency confusion", p.stderr)

    def test_cyclic_and_missing(self):
        a = os.path.join(self.t, "a"); b = os.path.join(self.t, "b")
        mkpkg(a, "pa", "1.0.0", "", 'pb = { path = "../b" }\n'); mkpkg(b, "pb", "1.0.0", "", 'pa = { path = "../a" }\n')
        app = self.proj(); p = qh(["add", "--path", "../a", "pa"], app)
        self.assertNotEqual(p.returncode, 0); self.assertIn("melingkar", p.stderr)


    def test_caret_version_ranges_follow_semver(self):
        os.makedirs(self.reg, exist_ok=True)
        idx = {"packages": {"demo": {"versions": {v: {"file": f"demo-{v}.qhpkg", "sha256": "x"} for v in ("0.0.3", "0.0.4", "0.1.0", "0.2.0", "0.9.0", "1.0.0", "1.2.0", "1.9.0", "2.0.0")}}}}
        with open(os.path.join(self.reg, "index.json"), "w", encoding="utf-8") as f:
            json.dump(idx, f)
        self.assertEqual(registry.resolve(self.reg, "demo", "^0.0.3")[0], "0.0.3")
        self.assertEqual(registry.resolve(self.reg, "demo", "^0.1.0")[0], "0.1.0")
        self.assertEqual(registry.resolve(self.reg, "demo", "^1.2.0")[0], "1.9.0")
        with self.assertRaises(QichError):
            registry.resolve(self.reg, "demo", "^bad")

    def test_dependency_name_path_traversal_rejected(self):
        app = self.proj()
        manifest_path = os.path.join(app, "qh.toml")
        text = open(manifest_path, encoding="utf-8").read()
        text = text.replace("[dependencies]", '[dependencies]\n"../../outside" = { path = "../mylib" }', 1)
        open(manifest_path, "w", encoding="utf-8").write(text)
        p = qh(["run"], app)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("nama dependensi tidak valid", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.t, "outside")))

    def test_bridge_allow_is_recorded_not_installed(self):
        app = self.proj(); p = qh(["add", "py:numpy"], app); self.assertEqual(p.returncode, 0)
        self.assertIn('py:numpy', open(os.path.join(app, "qh.toml")).read()); self.assertIn("tidak meng-install", p.stdout)

    def test_unknown_module_path_traversal(self):
        app = self.proj()
        w(os.path.join(app, "src", "main.qh"), 'use mod:..secret\nfn main() { }\n')
        self.assertNotEqual(qh(["run"], app).returncode, 0)


if __name__ == "__main__":
    unittest.main()
