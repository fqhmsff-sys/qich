# Changelog

Perubahan penting untuk pengguna Qich dicatat di sini.

## 0.2.1 — 2026-10-20

- Optimalkan lookup variabel runtime untuk menghindari dua pencarian dictionary pada binding yang ditemukan.
- Tambahkan tes untuk nilai `nil` dan shadowing variabel.
- Jalankan benchmark interpreter sebagai smoke test CI.

## Unreleased

- Perketat validasi versi artifact `.qhc` agar boolean tidak diterima sebagai versi integer.
- Perbaiki tes keamanan artifact agar payload malformed diuji dengan header dan checksum yang valid.
- Tambahkan pemeriksaan build wheel dan source distribution ke GitHub Actions.
- Tambahkan checklist kesiapan rilis dan perjelas status instalasi paket pada dokumentasi.
- Batasan tetap berlaku: checksum `.qhc` bukan tanda tangan digital; bridge Python bukan sandbox; platform selain Linux belum diverifikasi CI.
