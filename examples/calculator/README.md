# Qich Calc

Kalkulator web responsif dengan UI dark premium, dibuat sebagai contoh aplikasi di repository Qich.

## Jalankan

Buka `index.html` langsung di browser, atau jalankan server statis dari folder ini:

```sh
python3 -m http.server 8080
```

Lalu buka `http://localhost:8080`.

## Fitur

- Operasi dasar: tambah, kurang, kali, bagi
- Persen, ubah tanda, desimal, reset, dan backspace lewat keyboard
- Riwayat perhitungan tersimpan di `localStorage`
- Layout responsif untuk ponsel dan desktop
- Tidak membutuhkan dependency atau build step

**Catatan:** UI saat ini adalah web app mandiri HTML/CSS/JavaScript. Ini bukan native Android build dan belum menggunakan runtime Qich untuk logika di browser; dukungan event handler generator aplikasi Qich masih terbatas.
