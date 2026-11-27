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
| QVM1 bytecode versioned + reference stack executor | EXPERIMENTAL | compiler subset AST → QVM1 dan executor referensi masih Python; lihat BOOTSTRAP.md |
| QVM1 verifier/executor source prototype dalam Qich | EXPERIMENTAL | `bootstrap/qvm1.qh` diuji melalui reference runtime; belum native executable atau bootstrap mandiri |
| Native bootstrap seed QVM1 | EXPERIMENTAL | `bootstrap/native/qvm1_seed.c`; mendukung nil/bool/string dan signed integer hingga 13.000 bit (OpenSSL BIGNUM), ADD/SUB/MUL/MOD/NEG, equality/comparison, local dan branch terbatas. Build-time C + OpenSSL `libcrypto` + `json-c`; bukan full-conformance atau runtime final. Suite native: 21 test methods, 37 kasus differential bernama, 64 malformed-payload fuzz-smoke cases; ASan/UBSan pada Linux CI. |
| Native compiler/runtime, self-hosted compiler, GC sendiri | PLANNED | toolchain mandiri belum tersedia; memori reference runtime masih dikelola Python |
| Compiler/runtime Qich-native dan self-hosted | PLANNED | source akhir wajib Qich; bootstrap seed C/Rust hanya build-time sementara, bukan runtime host permanen |
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
Lihat `security/SECURITY.md` — tiap klaim ada test. QVM1 memiliki batas bytecode, stack, langkah, ukuran integer, dan pool integer; ini bukan batas RSS/CPU tingkat proses. Belum ada: signed releases (PLANNED), batas memori/CPU proses, isolasi proses untuk `py:`, registry HTTPS/TUF.

## Kemandirian

Qich **belum mandiri**. QVM1 reference compiler/verifier/executor masih Python berstatus EXPERIMENTAL. Seed C native menjalankan subset QVM1 yang terbatas, termasuk signed BigInt hingga 13.000 bit, tetapi belum full-conformance dan masih bergantung pada C compiler/OpenSSL/`json-c` saat build-time. Compiler utama, runtime/VM penuh, package tooling inti, dan minimum stdlib masih membutuhkan Python sebagai host. Tenggat final kemandirian adalah **14 Desember 2026**; gerbang penerimaan dan tahapan bootstrap ada di [BOOTSTRAP.md](BOOTSTRAP.md). Tidak ada klaim self-hosting sebelum clean-room build tanpa Python/Node dan stage0 → stage1 → stage2 lulus.
