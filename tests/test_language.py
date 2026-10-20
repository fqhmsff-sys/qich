import unittest
from helpers import run, parse, QichError
from qich.compiler.fmt import format_source
from qich.compiler.semantic import check_program
from qich.compiler import qhc, ast as A


class Lang(unittest.TestCase):
    def test_hello(self):
        self.assertEqual(run('fn main() { print("Hello Qich") }\nmain()'), "Hello Qich\n")

    def test_blueprint_syntax(self):
        out = run('''let nama = "Budi"
let umur = 25
let daftar = [1, 2, 3]
fn plus(a, b) rtrn => a + b
fn sapa(nama) {
    rtrn "Halo, " + nama
}
fn cek(umur) {
    if umur > 18 {
        rtrn "dewasa"
    } else {
        rtrn "muda"
    }
}
print(plus(1, 2), sapa(nama), cek(umur))
print(umur > 18 ? "dewasa" : "muda")
for i in 0..3 { print(i) }
for item in daftar { print(item) }''')
        self.assertEqual(out.split("\n")[0], "3 Halo, Budi dewasa")
        self.assertIn("dewasa", out)

    def test_syntax_error_diagnostic(self):
        with self.assertRaises(QichError) as c: parse("fn x( {", "a.qh")
        self.assertEqual(c.exception.kind, "SyntaxError"); self.assertIsNotNone(c.exception.line)

    def test_checker_reports(self):
        errs, w = check_program(parse('let a = 1\nprint(b)\nfn f(x: int) rtrn => x\nf("s")\nrtrn 1', "a.qh"), "a.qh")
        codes = {e.code for e in errs}
        self.assertTrue({"E0101", "E0204", "E0103"} <= codes)

    def test_exhaustiveness_warning(self):
        _, w = check_program(parse('enm S { A, B }\nlet x = mtch A { A => 1 }', "a.qh"), "a.qh")
        self.assertEqual([x.code for x in w], ["W0301"])

    def test_formatter_idempotent_keeps_comments(self):
        src = 'fn f(){\nlet x=1 // komentar\nif x==1{\nprint("a{")\n}\n}\n\n\n\n'
        a = format_source(src); b = format_source(a)
        self.assertEqual(a, b); self.assertIn("// komentar", a)

    def test_qhc_roundtrip_and_tamper(self):
        prog = parse('print(1)', "a.qh")
        data = qhc.dump({"|entry|": {"file": "a.qh", "pkg": None, "program": prog}}, "|entry|")
        mods, entry, _ = qhc.load(data); self.assertEqual(mods[entry]["program"], prog)
        with self.assertRaises(ValueError): qhc.load(data[:-3] + b"xxx")      # checksum
        with self.assertRaises(ValueError): qhc.load(b"BAD" + data)           # magic

    def test_qhc_verifier_rejects_unknown_nodes(self):
        with self.assertRaises(ValueError): A.from_dict({"t": "Evil", "cmd": "rm"})
        with self.assertRaises(ValueError): A.from_dict({"t": "Num", "value": 1, "extra": 2})
        with self.assertRaises(ValueError): A.from_dict({"t": "Str", "value": 5})

    def test_iterating_maps_strings_and_bytes(self):
        src = 'let m = {"a": 1, "b": 2}\nfor k, v in m { print(k, v) }\nfor c in "ab" { print(c) }\nfor b in bytes([65, 66]) { print(b) }'
        out = run(src)
        self.assertEqual(out, "a 1\nb 2\na\nb\n65\n66\n")

    def test_task_errors_propagate(self):
        out = run('async fn f() { rtrn [1][9] }\ntry { await f() } catch e { print(e.kind) }')
        self.assertEqual(out.strip(), "IndexError")


if __name__ == "__main__":
    unittest.main()
