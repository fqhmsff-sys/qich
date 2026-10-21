# Qich Language Support for Acode

Integrasi awal bahasa Qich untuk editor Acode Android.

## Fitur

- Mengenali file `.qh` dan mendaftarkan mode syntax highlighting Qich.
- Highlight keyword, string, komentar, angka, tipe, dan nama fungsi.
- Tombol ▶ Run saat file `.qh` aktif.
- Command **Run current Qich file** (shortcut Ctrl+Alt+R jika keyboard mendukung).
- Menjalankan kode dengan `qh run` di terminal bawaan Acode, sehingga pesan error compiler/runtime Qich ditampilkan di terminal.

## Persyaratan

- Acode versi yang mendukung plugin API pada manifest (minimum version code 963).
- Terminal bawaan Acode sudah disiapkan: buka Menu → Terminal dan ikuti setup yang diminta.
- Qich CLI `qh` dan Python 3.11+ tersedia **di lingkungan terminal Acode**. Instalasi Qich di Termux atau Python lain tidak otomatis tersedia di terminal Acode.

## Instal plugin di HP Android

### 1. Unduh ZIP plugin

1. Buka [workflow Build Qich Acode Plugin](https://github.com/fqhmsff-sys/qich/actions/workflows/acode-plugin.yml).
2. Buka run terbaru yang berstatus **Success**. Jika belum ada, tunggu workflow selesai setelah perubahan terbaru masuk ke `main`.
3. Di bagian **Artifacts**, unduh `qich-acode-plugin`.
4. Ekstrak ZIP hasil unduhan. Di dalamnya ada file `qich-acode-plugin.zip`. **Jangan ekstrak ZIP plugin yang di dalam**—file itu yang akan dipasang di Acode.

### 2. Pasang plugin di Acode

1. Buka Acode.
2. Masuk ke **Settings → Plugins**.
3. Tekan tombol **+**, lalu pilih **LOCAL**.
4. Pilih file `qich-acode-plugin.zip` yang tadi ditemukan setelah ekstraksi.
5. Selesaikan proses instalasi, lalu tutup dan buka ulang file editor jika diperlukan.

### 3. Siapkan Qich CLI di terminal Acode

Buka terminal bawaan Acode. Pastikan terminal tersebut sudah selesai disiapkan, lalu jalankan:

```sh
apk update
apk add python3 py3-pip py3-virtualenv git
git clone https://github.com/fqhmsff-sys/qich.git
cd qich
virtualenv ~/.venvs/qich
~/.venvs/qich/bin/pip install .
export PATH="$HOME/.venvs/qich/bin:$PATH"
qh --version
```

Jika folder `qich` sudah ada di terminal, masuk ke folder tersebut dan jalankan langkah mulai `virtualenv` tanpa mengulang `git clone`.

Agar perintah `qh` tersedia setiap terminal dibuka, tambahkan baris berikut ke skrip startup terminal Acode jika lingkungan Acode menyediakan skrip tersebut:

```sh
export PATH="$HOME/.venvs/qich/bin:$PATH"
```

Jika perintah `apk` tidak tersedia, berarti terminal yang terbuka bukan lingkungan Alpine yang digunakan petunjuk ini. Jangan lanjutkan perintah instalasi Alpine di terminal yang berbeda.

### 4. Tes plugin

1. Buka atau buat file dengan ekstensi `.qh`.
2. Pastikan keyword, string, komentar, dan angka diberi warna. Jika belum, cek versi Acode dan apakah plugin aktif.
3. Simpan file terlebih dahulu.
4. Tekan tombol ▶ **Run** di header editor.
5. Terminal Qich akan terbuka dan menjalankan `qh run` pada file tersebut. Periksa output atau pesan error di terminal.
6. Tes juga perintah manual `qh --version` dan `qh run nama_file.qh` di terminal, dari direktori yang bisa diakses terminal.

## Membuat ZIP plugin dari source

Dari root repository Qich, jalankan:

```sh
python3 integrations/acode/package_plugin.py
```

ZIP dibuat di `integrations/acode/dist/qich-acode-plugin.zip`. Isi ZIP harus memiliki `plugin.json`, `main.js`, dan `readme.md` langsung di root arsip.

## Batasan yang perlu diketahui

- Plugin ini belum diverifikasi langsung di perangkat Android. API Acode, akses file, dan konfigurasi terminal dapat berbeda antar versi/perangkat.
- GitHub Actions memeriksa sintaks JavaScript, manifest, dan isi ZIP; itu tidak bisa membuktikan plugin berjalan di semua perangkat.
- File tersimpan dijalankan dari path aslinya agar konteks proyek dan impor relatif tetap terjaga. Pastikan terminal Acode bisa mengakses lokasi file tersebut.
- File yang belum tersimpan dijalankan dari salinan sementara di `/tmp`; simpan file terlebih dahulu jika program menggunakan modul relatif.
- Highlighting hanya pewarnaan token, bukan pemeriksaan semantik. Pesan error berasal dari CLI Qich.
- Jika tombol Run tidak muncul atau terminal gagal, catat versi Acode dan pesan error yang tampil sebelum mengubah konfigurasi lain.
