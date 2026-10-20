# Status Qich v0.2.1

Legenda: **TESTED** = ada test otomatis yang lulus di lingkungan pengembangan (Linux, Python 3.11, Node 22, g++) ·
**IMPLEMENTED** = kode ada, belum teruji di sini · **EXPERIMENTAL** = ada, terbatas · **PLANNED** = belum ada · **UNAVAILABLE** = tidak bisa di lingkungan ini.

## Inti bahasa
| Komponen | Status | Catatan |
|---|---|---|
| Lexer, parser, AST, diagnostik (file:baris:kolom + kutipan + bantuan) | TESTED | |
| Analisis semantik (scope, arity, tipe literal, exhaustiveness `mtch`) | TESTED | peringatan W0301 untuk enm tak lengkap |
| Tipe opsional dicek saat ada, generics, kontrak `requires`/`ensures` | TESTED | dicek **saat runtime**; type checker statis penuh = PLANNED (statis: hanya literal/arity/nama) |
| Pattern matching, Result + `?`, try/catch/throw, async/await (thread) | TESTED | |
| Modul `use mod:`/`pkg:`, impor melingkar terdeteksi | TESTED | |
| Compiler → `.qhc` (AST ter-serialisasi + SHA-256, diverifikasi saat load) | TESTED | **bukan** bytecode VM atau native; lihat DECISIONS |
| Bytecode VM, kompilasi native, GC sendiri | PLANNED | memori dikelola Python (aman: tanpa UB, indeks dicek) |
| Core compiler/runtime dalam Rust | PLANNED / UNAVAILABLE di sandbox | tidak ada `rustc` di lingkungan pengembangan; implementasi referensi ini ditulis Python |
| Formatter (indentasi + spasi, idempoten, menjaga komentar), `qh doc` | TESTED | formatter berbasis baris, bukan pretty-printer AST |

## Toolchain
`qh new/run/build/test/add/remove/check/fmt/update/doc/clean/bundle/publish/audit/bridges/repl` — TESTED (end-to-end via subprocess).
Instalasi `install.sh` — TESTED (prefix sementara). `pip install .` — TESTED (CI install-smoke).

## Library standar & Qichy
| Modul | Status |
|---|---|
| `std:fs json os math time rand http` | TESTED |
| `qy` Tensor, Model feed-forward (backprop+SGD), data, simpan/muat JSON tervalidasi | TESTED (backend `python` murni) |
| `qy:lm` NgramLM (fondasi LLM tahap awal) | EXPERIMENTAL — n-gram, **bukan** transformer |
| `qy` backend numpy / torch / mesin C++ / GPU | PLANNED (GPU: UNAVAILABLE di sini) |
| `chyb:server/client` HTTP, routing, middleware, static, default aman | TESTED |
| `chyb` WebSocket, HTTP/2, TLS server | PLANNED |
| `qapp:ui` render teks & HTML headless, State, lifecycle, `qapp:storage` | TESTED |
| `qapp` jendela desktop (tkinter) | IMPLEMENTED — tidak teruji (tidak ada tkinter/display di sandbox) |
| `qapp` generator Kotlin (Android) & Swift (iOS/macOS) | IMPLEMENTED — keluaran string diuji, **tidak dikompilasi**; event handler di mobile = PLANNED |

## Bridge (lihat `qh bridges`)
`py` TESTED (in-process, bukan sandbox) · `js` TESTED (proses terpisah) · `c` TESTED (primitif+str) · `cpp` TESTED (hanya `extern "C"`).
Go, Rust, Java, Kotlin, Dart, Swift, C#, PHP, Ruby, R, Julia, Lua, Elixir, Erlang, Scala, Clojure, Haskell, OCaml, F#, Zig, Fortran, Perl, Groovy, Objective-C, VB, TypeScript: **PLANNED** — `use` memberi galat jujur, bukan pura-pura jalan.
Penambahan adapter = satu entri registry + satu modul adapter (tanpa mengubah compiler).

## Platform
Linux: TESTED. Windows, macOS: kode portabel (Python/stdlib) tetapi **tidak diuji**. Android, iOS: hanya generator source (IMPLEMENTED, tidak dikompilasi).

## Keamanan
Lihat `security/SECURITY.md` — tiap klaim ada test. Belum ada: signed releases (PLANNED), batas memori proses, isolasi proses untuk `py:`, registry HTTPS.
