# Qich Language Support for Acode

Integrasi awal bahasa Qich untuk editor Acode Android.

## Fitur

- Mengenali file `.qh` dan mendaftarkan mode syntax highlighting Qich.
- Highlight keyword, string, komentar, angka, tipe, dan nama fungsi.
- Tombol ▶ Run pada header ketika file `.qh` aktif.
- Command palette: **Run current Qich file** (shortcut Ctrl+Alt+R jika keyboard mendukung).
- Menjalankan kode dengan `qh run` di terminal bawaan Acode, sehingga error compiler/runtime Qich tampil di terminal.

## Persyaratan

1. Acode dengan terminal bawaan yang sudah disiapkan (Menu → Terminal).
2. Qich CLI `qh` terpasang **di lingkungan terminal Acode**, bukan hanya di Termux atau Python Android lain.
3. Python 3.11 atau lebih baru tersedia di lingkungan terminal.

## Memasang Qich di terminal Acode

Di terminal bawaan Acode, jalankan:

```sh
apk update
apk add python3 py3-pip git
git clone https://github.com/fqhmsff-sys/qich.git
cd qich
python3 -m venv ~/.venvs/qich
~/.venvs/qich/bin/pip install .
export PATH="$HOME/.venvs/qich/bin:$PATH"
qh --version
```

Untuk mempertahankan PATH pada sesi terminal berikutnya, tambahkan baris berikut ke skrip startup terminal Acode (misalnya `/initrc` jika tersedia):

```sh
export PATH="$HOME/.venvs/qich/bin:$PATH"
```

Pastikan Acode Terminal bisa mengakses direktori proyek. Kalau perintah `python3 -m venv` tidak tersedia, periksa paket Python/venv yang tersedia di repositori Alpine perangkatmu.

## Memasang plugin selama pengembangan

Plugin Acode harus berupa ZIP dengan `plugin.json` dan `main.js` di root ZIP.

Dari root repository Qich, jalankan:

```sh
python3 integrations/acode/package_plugin.py
```

Lalu di Acode: **Settings → Plugins → + → LOCAL**, pilih file ZIP yang dihasilkan. Setelah plugin terpasang, buka file `.qh` dan tekan ▶.

## Catatan penting

- Ini versi awal dan belum diuji langsung di perangkat Android. Acode dan lingkungan terminal berbeda antar versi/perangkat.
- File yang tersimpan dijalankan dari path aslinya, agar impor modul/proyek tetap punya konteks. File yang belum tersimpan dijalankan dari salinan sementara di `/tmp`; simpan file terlebih dahulu jika program memakai modul relatif.
- Highlighting adalah tokenisasi editor, bukan pemeriksaan semantik. Validasi dan pesan error tetap berasal dari CLI Qich.
