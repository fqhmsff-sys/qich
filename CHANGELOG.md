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
- Perketat ekstraksi arsip paket: tolak Windows drive/ADS, nama perangkat, segmen ambigu, collision lintas kapitalisasi, dan konflik file/direktori.
- Ekstrak anggota ZIP secara streaming dengan buffer 64 KiB dan batas ukuran aktual; tulis melalui file sementara sebelum mengganti target.
- Tolak symlink dan file khusus pada pohon dependensi lokal sebelum hashing/penyalinan, sehingga konten di luar paket tidak ikut tersalin diam-diam.
- Batasan tetap berlaku: checksum `.qhc` bukan tanda tangan digital; bridge Python bukan sandbox; platform selain Linux belum diverifikasi CI.
