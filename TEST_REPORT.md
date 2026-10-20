# Qich v0.2.0 — Perbaikan dan Hasil Pemeriksaan

Tanggal: 2026-10-20

## Identitas
- Logo konsep The Three Core tetap digunakan.
- Palet merah: `#E63946`, `#C92D3A`, `#F04452`, dengan charcoal `#172337`.
- Aset logo SVG/PNG dan ikon tanpa teks tetap tersedia di direktori `logo/`.
- Sintaks, kata kunci, dan gaya penulisan bahasa Qich tidak diubah.

## Perbaikan kode

1. **Validasi nama dependensi**
   - Resolver sekarang memvalidasi nama dependensi dengan aturan nama paket sebelum membuat path vendor.
   - Nama yang mengandung traversal seperti `../../outside` ditolak dengan diagnosis `P0004` sebelum dapat menulis ke luar direktori dependensi.
   - Tes regresi `test_dependency_name_path_traversal_rejected` ditambahkan.

2. **Rentang versi caret di package registry**
   - Resolver versi `^` sebelumnya hanya membatasi versi berdasarkan nomor major, sehingga versi `^0.x` dapat memilih versi yang tidak kompatibel.
   - Sekarang batas mengikuti aturan caret semver: `^1.2.0` mengizinkan `<2.0.0`, `^0.1.0` mengizinkan `<0.2.0`, dan `^0.0.3` mengizinkan `<0.0.4`.
   - Rentang caret yang tidak valid menghasilkan diagnosis `P0104` alih-alih diterima diam-diam.
   - Tes regresi `test_caret_version_ranges_follow_semver` ditambahkan.

## Hasil pengujian yang dijalankan

- `tests/test_language.py`, `tests/test_bridge.py`, `tests/test_security.py`: **29 lulus**.
- `tests/test_packages.py`: **11 lulus**.
- `tests/test_chyb_cli.py`: **10 lulus**.
- Tes bahasa Qich `.qh`: **17 lulus, 0 gagal**.
- `python -m compileall -q src tests`: berhasil.
- Instalasi editable berhasil dengan `pip install -e . --no-build-isolation --no-deps` pada lingkungan ini.
- Contoh `examples/hello`, `examples/ai-xor`, `examples/web-api`, dan `examples/app-counter` diuji lewat suite CLI.

Ketiga modul tes Python dijalankan terpisah dan semuanya lulus (total 50 tes). Satu eksekusi gabungan seluruh `pytest` melewati batas waktu lingkungan, sehingga hasil gabungan tersebut tidak diklaim lulus; hasil tiap modul tetap dicatat secara terpisah di atas.

## Batasan lingkungan

- Instalasi `pip install -e .` dengan build isolation tidak dapat mengunduh build dependency karena lingkungan uji tidak memiliki akses jaringan. Ini adalah batasan jaringan saat pengujian, bukan bukti bahwa paket membutuhkan perubahan kode.
- Dukungan produksi untuk semua target Android/iOS, web, dan AI belum dapat disimpulkan hanya dari tes ini; target-target tersebut perlu diuji pada lingkungan runtime masing-masing.
