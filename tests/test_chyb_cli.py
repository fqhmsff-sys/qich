import os, shutil, tempfile, unittest, urllib.request, urllib.error, socket
from helpers import run, qh, ROOT


class Chyb(unittest.TestCase):
    def test_static_traversal_and_limits(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "pub")); open(os.path.join(d, "pub", "a.txt"), "w").write("publik")
            open(os.path.join(d, "rahasia.txt"), "w").write("RAHASIA")
            out = run(f'''use chyb:server
use chyb:client
let app = Server(max_body: 100)
app.static("/files", "{d}/pub")
app.post("/x", fn(req) rtrn => "ok")
let h = app.start(0)
let b = "http://127.0.0.1:" + str(h.port)
print(get(b + "/files/a.txt").unwrap().text())
print(get(b + "/files/../rahasia.txt").unwrap().status)
print(get(b + "/files/%2e%2e/rahasia.txt").unwrap().status)
print(post(b + "/x", "a" * 1000).unwrap().status)
print(post(b + "/x", "ok").unwrap().status)
print(get(b + "/files/a.txt").unwrap().headers["x-frame-options"])
h.stop()''')
            self.assertEqual(out.split("\n")[:6], ["publik", "403", "403", "413", "200", "DENY"])

    def test_error_details_not_leaked_and_bind_loopback(self):
        out = run('''use chyb:server
use chyb:client
let app = Server()
app.get("/e", fn(req) { throw "rahasia-internal" })
app.get("/e2", fn(req) rtrn => Err(Error("db-password=abc")))
let h = app.start(0)
let b = "http://127.0.0.1:" + str(h.port)
let r = get(b + "/e").unwrap()
let r2 = get(b + "/e2").unwrap()
print(r.status, r.text())
print(r2.status, r2.text())
print(h.host)
h.stop()''')
        self.assertEqual(out.split("\n")[:3], ["500 Internal Server Error", "500 Internal Server Error", "127.0.0.1"])

    def test_redirect_and_header_injection_blocked(self):
        out = run('''use chyb:server
let ok = Response.redirect("/aman")
print(ok.code)
try { Response.redirect("javascript:alert(1)") } catch e { print("blok") }
try { Response.text("x").header("X-A", "v\\r\\nSet-Cookie: a=b") } catch e { print("blok") }''')
        self.assertEqual(out.split(), ["302", "blok", "blok"])

    def test_slowloris_style_malformed_request_does_not_crash_server(self):
        out = run('use chyb:server\nuse chyb:client\nlet app = Server()\napp.get("/", fn(req) rtrn => "hidup")\nlet h = app.start(0)\nprint(h.port)\n')
        # server baru untuk uji raw socket
        from qich.chyb import Server
        class FakeI:
            def call(self, f, a): return "hidup"
        s = Server(); s.I = FakeI(); s.get("/", object()); h = s.start(0)
        try:
            for raw in (b"GARBAGE\r\n\r\n", b"GET / HTTP/1.1\r\nContent-Length: -5\r\n\r\n", b"GET / HTTP/1.1\r\nContent-Length: abc\r\n\r\n", b"\x00\xff" * 100):
                c = socket.create_connection(("127.0.0.1", h.port), timeout=3); c.sendall(raw)
                try: c.recv(1024)
                except OSError: pass
                c.close()
            r = urllib.request.urlopen(f"http://127.0.0.1:{h.port}/", timeout=3); self.assertEqual(r.read(), b"hidup")
        finally: h.stop()


class CLI(unittest.TestCase):
    def setUp(self): self.t = tempfile.mkdtemp()
    def tearDown(self): shutil.rmtree(self.t, ignore_errors=True)

    def test_full_workflow_commands(self):
        self.assertEqual(qh(["new", "my-app"], self.t).returncode, 0)
        app = os.path.join(self.t, "my-app")
        p = qh(["run"], app); self.assertEqual(p.stdout, "Hello Qich\nHalo, dunia!\n")
        self.assertIn("2 lulus", qh(["test"], app).stdout)
        self.assertEqual(qh(["check"], app).returncode, 0)
        self.assertEqual(qh(["fmt"], app).returncode, 0)
        self.assertEqual(qh(["doc"], app).returncode, 0)
        self.assertTrue(os.path.isfile(os.path.join(app, "build", "doc", "src_main.qh.md")))
        self.assertEqual(qh(["build"], app).returncode, 0)
        self.assertEqual(qh(["run", "build/my-app.qhc"], app).stdout, "Hello Qich\nHalo, dunia!\n")
        self.assertEqual(qh(["bundle"], app).returncode, 0)
        import subprocess, sys
        self.assertEqual(subprocess.run([sys.executable, os.path.join(app, "build", "my-app.pyz")], capture_output=True, text=True).stdout, "Hello Qich\nHalo, dunia!\n")
        self.assertEqual(qh(["clean"], app).returncode, 0); self.assertFalse(os.path.exists(os.path.join(app, "build")))

    def test_diagnostics_human_readable_and_exit_codes(self):
        qh(["new", "bad"], self.t); app = os.path.join(self.t, "bad")
        open(os.path.join(app, "src", "main.qh"), "w").write('fn main() {\n    print(nama_salah)\n}\n')
        p = qh(["run"], app); self.assertEqual(p.returncode, 1)
        self.assertIn("error[E0101]", p.stderr); self.assertIn("src/main.qh:2", p.stderr); self.assertIn("^^^", p.stderr)
        open(os.path.join(app, "src", "main.qh"), "w").write('fn main() {\n    let x = [1][5]\n}\n')
        p = qh(["run"], app); self.assertEqual(p.returncode, 1); self.assertIn("di luar batas", p.stderr); self.assertIn("jejak", p.stderr)
        open(os.path.join(app, "src", "main.qh"), "w").write('fn main() {\n    print("x"\n}\n')
        p = qh(["run"], app); self.assertEqual(p.returncode, 1); self.assertIn("SyntaxError" if "SyntaxError" in p.stderr else "error[E", p.stderr)

    def test_failing_test_reports_nonzero(self):
        qh(["new", "t"], self.t); app = os.path.join(self.t, "t")
        open(os.path.join(app, "tests", "x_test.qh"), "w").write('fn test_gagal() { assert_eq(1, 2) }\n')
        p = qh(["test"], app); self.assertEqual(p.returncode, 1); self.assertIn("FAIL", p.stdout)

    def test_corrupt_qhc_refused(self):
        qh(["new", "c"], self.t); app = os.path.join(self.t, "c"); qh(["build"], app)
        f = os.path.join(app, "build", "c.qhc"); d = bytearray(open(f, "rb").read()); d[-10] ^= 0xFF; open(f, "wb").write(d)
        p = qh(["run", "build/c.qhc"], app); self.assertEqual(p.returncode, 1); self.assertIn("checksum", p.stderr)

    def test_example_projects_pass(self):
        for name in ("hello", "ai-xor", "web-api", "app-counter"):
            d = os.path.join(ROOT, "examples", name)
            if os.path.isdir(d):
                p = qh(["test"], d); self.assertEqual(p.returncode, 0, name + p.stdout + p.stderr)

    def test_repo_qh_tests(self):
        p = qh(["test"], ROOT); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
