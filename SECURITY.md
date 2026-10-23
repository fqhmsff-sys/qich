# Security Policy

Dokumen teknis model ancaman ada di [security/SECURITY.md](security/SECURITY.md).

## Melaporkan kerentanan

Jangan membuka detail eksploit sebagai issue publik. Gunakan GitHub Security Advisory privat untuk repository ini.

## Prinsip

Qich memperlakukan source, package, artifact, bridge, model, arsip, path, network input, dan file proyek sebagai input yang dapat tidak tepercaya. Semua parser/loader harus gagal tertutup, memiliki batas resource, dan menghindari eksekusi implisit.

Tidak ada software yang bisa dijanjikan "tanpa bug". Target proyek adalah menemukan, memperbaiki, menguji regresi, dan memperkecil blast radius secara terus-menerus.
