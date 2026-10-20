# Referensi bahasa Qich

```
// komentar        /// dokumentasi (dipakai qh doc)
use std:fs   use py:math   use mod:util   use pkg:mylib   use qy:model

let nama = "Budi"            let umur: int = 25       let xs = [1, 2, 3]       let m = {a: 1, "b": 2}
fn plus(a, b) rtrn => a + b                     // ekspresi satu baris
fn sapa(n: str, salam = "Halo") -> str { rtrn f"{salam}, {n}" }
fn akar(n: int) -> int requires n >= 0 ensures result >= 0 { ... }
fn pertama<T>(xs: list<T>) -> T rtrn => xs[0]    // generics
async fn kerja(n) { rtrn n * 2 }                 // await kerja(3)

if a > b { } else if a == b { } else { }         umur > 18 ? "dewasa" : "muda"
for i in 0..10 { }   for x in xs { }   for k, v in m { }   whl cond { brk / cnt }

strct Point { x: int  y: int  fn sum(self) rtrn => self.x + self.y }
enm Shape { Circle(r), Rect(w, h), Dot }
mtch s { Circle(r) if r > 0 => r, Rect(w, h) => w * h, [a, ..rest] => 1, 1..=5 => 2, "a" | "b" => 3, _ => 0 }

fn baca() { let teks = fs.read("x")?   rtrn Ok(teks) }          // ? meneruskan Err
try { throw "x" } catch e { print(e) }
```
Tipe: `int float str bool nil list map fn bytes any Result Task` + `strct`/`enm` + `T?` (nullable). Anotasi opsional; dicek saat ada.
Operator: `+ - * / % == != < > <= >= && || ! in .. ..=`; `/` selalu float; `1..3` eksklusif, `1..=3` inklusif; slicing `xs[1..3]`.
Aturan satu baris: `+`/`-` di awal baris memulai pernyataan baru; `(`/`[` di awal baris tidak memanggil/mengindeks.
