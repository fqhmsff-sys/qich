# Bridge

Jalankan `qh bridges` untuk tabel kapabilitas aktual. TESTED: `py`, `js`, `c`, `cpp` (extern "C"). Sisanya PLANNED dan menghasilkan galat jujur.
Menambah ekosistem: tambahkan entri di `bridge/registry.py` dan modul adapter yang menerjemahkan nilai, panggilan, objek, galat, callback, dan memori.

Konversi: `py` — primitif/list/dict disalin, objek lain dibungkus `PyRef` (anggota privat `_x` diblokir); `js` — data JSON-like disalin, selain itu handle di proses node; `c` — hanya `i32 i64 u32 u64 usize f32 f64 bool str void`, tanpa pointer mentah, rentang argumen dicek.
`Secret` tidak pernah melintasi bridge. Modul berbahaya (`py:os`, `py:subprocess`, `js:child_process`, …) diblokir kecuali diizinkan di `qh.toml [bridge] allow` atau `--allow`.
