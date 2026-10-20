# Keputusan & resolusi konflik

Blueprint (Master Blueprint Revisi v2) adalah sumber kebenaran. Hal yang tidak ditentukan diputuskan di sini.

1. **Host implementasi fase awal = Python, bukan Rust.** Blueprint menetapkan Rust sebagai fondasi core; lingkungan pengembangan tidak punya `rustc` (dan jaringan nonaktif), sehingga core tidak bisa dibangun/diuji dengan jujur. Implementasi referensi ini ditulis dengan Python murni (tanpa dependensi) agar benar-benar berjalan dan teruji. Arsitektur (lexer→parser→AST→checker→IR→runtime) dipisah bersih agar bisa di-port ke Rust. Status: Rust core = PLANNED.
2. **`.qhc` = IR terverifikasi, bukan bytecode.** AST ter-serialisasi JSON + SHA-256 + whitelist node. Checksum mendeteksi korupsi; keaslian (signature) PLANNED.
3. **Blok `{}` kanonik** (sesuai blueprint). Contoh `fn main():` di prompt tidak dipakai; blueprint menang.
4. **Kontrak** memakai `requires` / `ensures` (nama `result` tersedia di `ensures`). Blueprint tidak menentukan sintaks; `req`/`post` ditolak karena bentrok dengan nama variabel umum (`req`, `post`).
5. **`enm`** (enum, singkatan sesuai aturan "tanpa vokal") ditambahkan untuk pattern matching. Varian ikut masuk scope.
6. **Strict bool**: `if`/`whl`/`!`/`&&`/`||`/ternary butuh `bool` (aman, error eksplisit). `+` tidak mengonversi implisit; pakai `str(x)` atau `f"..."`.
7. **Interpolasi** `f"...{ekspr}..."`. Kunci map `{a: 1}` = string `"a"`.
8. **`use eco:lib`**: `std/qy/chyb/qapp` internal; `mod:` = file proyek (`src/`), `pkg:` = dependensi `qh.toml`; selain itu bridge. Modul Qichy menyuntik nama ekspornya (mis. `use qy:model` → `Model`, `Dense`).
9. **Result**: fungsi std yang bisa gagal mengembalikan `Ok/Err`; `?` meneruskan `Err`.
10. **Async** = thread nyata (`async fn` mengembalikan task; `await` join). Channel `chan()`.
11. **Paket**: tidak ada install-script (paket murni sumber). Registry saat ini direktori lokal (`QH_REGISTRY`); HTTPS PLANNED. `qh add py:x` hanya mencatat izin bridge — tidak memasang paket asing.
12. **Typosquatting/dependency confusion**: nama mirip (Damerau-Levenshtein ≤1 atau normalisasi homoglif) ditolak saat publish/add; sumber di `qh.lock` terkunci; nama cadangan (`std qy chyb qapp ...`) ditolak.
13. **qy/LLM**: backend `python` murni; `NgramLM` sebagai fondasi bahasa; transformer = PLANNED.
