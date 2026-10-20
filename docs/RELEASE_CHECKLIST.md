# Checklist rilis Qich

Dokumen ini memisahkan pemeriksaan yang sudah otomatis dari pekerjaan yang masih membutuhkan lingkungan atau keputusan pemilik proyek.

## Sebelum setiap rilis

- [ ] Pastikan semua job GitHub Actions lulus pada commit yang akan dirilis.
- [ ] Jalankan tes Python dan tes bahasa Qich dari checkout bersih.
- [ ] Uji instalasi paket dengan `python -m pip install .` dan `qh --version`.
- [ ] Buat proyek baru, lalu jalankan `qh run`, `qh test`, `qh build`, dan jalankan artifact `.qhc`.
- [ ] Periksa perubahan dokumentasi, contoh, dan `docs/STATUS.md`.
- [ ] Perbarui versi secara konsisten di `pyproject.toml`, dokumentasi status, dan changelog.
- [ ] Tulis changelog untuk perubahan yang terlihat pengguna dan isu yang diketahui.
- [ ] Buat tag versi hanya setelah pemeriksaan di atas selesai.

## Sebelum menyebut rilis siap produksi

- [ ] Uji instalasi dan contoh proyek pada Linux, Windows, dan macOS; saat ini dukungan non-Linux belum diverifikasi CI.
- [ ] Uji paket wheel/sdist yang benar-benar dibangun dan dipasang dari artefak, bukan hanya instalasi dari source tree.
- [ ] Tambahkan fuzz/property tests untuk parser, AST dan loader artifact.
- [ ] Tinjau batas resource dan threat model untuk bridge Python; bridge Python berjalan in-process dan bukan sandbox.
- [ ] Tentukan dan implementasikan mekanisme signing/verifikasi rilis sebelum mengklaim asal paket terautentikasi.
- [ ] Pastikan setiap fitur yang didokumentasikan sesuai status IMPLEMENTED/TESTED/EXPERIMENTAL/PLANNED.

## Batasan yang diketahui

- `.qhc` menyertakan checksum SHA-256 untuk mendeteksi perubahan isi, bukan tanda tangan digital. Checksum bukan bukti siapa pembuat artifact.
- Type checking statis penuh, bytecode VM, kompilasi native, dan garbage collector sendiri belum tersedia.
- Adapter bridge selain Python, JavaScript, C dan C++ yang tercantum sebagai TESTED belum tersedia.
- Generator Android/iOS belum berarti aplikasi native telah dikompilasi atau diuji pada perangkat.
