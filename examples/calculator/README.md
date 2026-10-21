# Qich Calc

Kalkulator yang logika dan programnya ditulis dalam **Qich** (`.qh), bukan JavaScript atau Python.

## Fitur

- Operasi tambah, kurang, kali, dan bagi
- Validasi pembagian dengan nol
- Riwayat perhitungan selama program berjalan
- Menu interaktif: hitung, lihat riwayat, hapus riwayat, keluar
- Penanganan error agar program tetap berjalan

## Menjalankan

Pastikan Qich sudah dipasang dan perintah `qh` tersedia. Dari root repository:

```sh
qh run examples/calculator
```

Jika CLI di instalasimu menerima jalur file secara langsung, jalankan file `main.qh` dari folder ini sesuai sintaks `qh run` pada versi Qich yang terpasang.

## Catatan UI

Versi ini sengaja menggunakan antarmuka terminal karena event handler UI mobile Qich masih berstatus **PLANNED** di `docs/STATUS.md`. Jadi ini benar-benar program Qich yang bisa dikembangkan dan diuji, bukan web app HTML/JavaScript yang diklaim sebagai Qich. UI grafis premium dan APK Android native belum bisa dijanjikan berfungsi sampai dukungan event UI Android Qich selesai.
