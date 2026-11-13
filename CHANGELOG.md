# Changelog

Perubahan penting untuk pengguna Qich dicatat di sini.

## 0.2.1 — 2026-10-20

- Optimalkan lookup variabel runtime untuk menghindari dua pencarian dictionary pada binding yang ditemukan.
- Tambahkan tes untuk nilai `nil` dan shadowing variabel.
- Jalankan benchmark interpreter sebagai smoke test CI.

## Unreleased

- Tambahkan `bootstrap/qvm1.qh`: prototype verifier dan executor QVM1 yang ditulis dalam Qich, dengan differential tests terhadap reference VM. Source ini masih dijalankan melalui Python reference runtime dan belum menjadi native bootstrap.
- Integrasikan QVM1 versioned bytecode, verifier, reference executor, subset compiler, prepared execution, differential corpus, dan benchmark ke branch Qich v2. QVM tetap EXPERIMENTAL dan masih berjalan di Python; belum ada klaim native/self-hosted.
- Perketat publikasi paket dengan membuka file sumber melalui descriptor no-follow, mencocokkan identitas file dengan fstat, dan membatasi jumlah byte aktual yang di-stream ke ZIP agar pergantian symlink atau pertumbuhan file setelah stat tidak melewati batas.
- Normalisasi denylist JavaScript untuk builtin Node, termasuk awalan node: dan subpath, serta tambah regression tests protokol bridge.
- Tolak root path dependency yang berupa symlink sebelum realpath; pemeriksaan hash tidak boleh dilewati dengan mengkanonisasi symlink terlebih dahulu.
- Perketat validasi versi artifact `.qhc` agar boolean tidak diterima sebagai versi integer.
- Perbaiki tes keamanan artifact agar payload malformed diuji dengan header dan checksum yang valid.
- Tambahkan pemeriksaan build wheel dan source distribution ke GitHub Actions.
- Tambahkan checklist kesiapan rilis dan perjelas status instalasi paket pada dokumentasi.
- Perketat ekstraksi arsip paket: tolak Windows drive/ADS, nama perangkat, segmen ambigu, collision lintas kapitalisasi, dan konflik file/direktori.
- Ekstrak anggota ZIP secara streaming dengan buffer 64 KiB dan batas ukuran aktual; tulis melalui file sementara sebelum mengganti target.
- Tolak symlink dan file khusus pada pohon dependensi lokal sebelum hashing/penyalinan, sehingga konten di luar paket tidak ikut tersalin diam-diam.
- Perbarui action CI checkout, setup-python, upload-artifact, dan release ke rilis berbasis Node 24 agar tidak bergantung pada runtime Node 20 yang deprecated.
- Batasan tetap berlaku: checksum `.qhc` bukan tanda tangan digital; bridge Python bukan sandbox; platform selain Linux belum diverifikasi CI.
- Gagal tertutup saat enumerasi pohon paket tidak lengkap: hashing dependensi dan publikasi registry tidak boleh menerima hash/arsip parsial jika traversal direktori menghasilkan error.
- Samakan batas digit komponen versi `qh.lock` dengan registry agar versi lockfile malformed ditolak sebelum resolusi.
- Tolak direktori vendor `.qh/deps`, entri dependensi, akar hashing, dan tujuan ekstraksi ZIP yang berupa symlink; buat serta validasi direktori vendor tanpa mengikuti symlink.
- Lindungi `qh.lock` dari symlink saat dibaca/ditulis, batasi ukurannya, dan tulis pembaruan secara atomik.
- Validasi `qh.lock` versi 1 secara ketat: tolak versi/field yang tidak dikenal, entri paket duplikat, metadata malformed, dan digest SHA-256 yang tidak valid; serialisasi string TOML dengan escaping agar path tidak dapat menyisipkan tabel lock baru.
- Perbaiki kesetaraan opcode QVM1 pada source bootstrap Qich agar boolean tidak dianggap sama dengan integer, selaras dengan semantik `q_eq` pada reference runtime; tambahkan differential regression cases untuk EQ/NE, int-float, string-number, dan nil-bool.
- Eksekusi QVM one-shot sekarang memverifikasi snapshot immutable, bukan objek mutable milik caller, untuk menutup celah perubahan bytecode di antara validasi dan eksekusi; benchmark membedakan biaya snapshot+validasi dari prepared execution.
