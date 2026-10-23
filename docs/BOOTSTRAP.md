# Qich: jalur menuju toolchain mandiri

Qich tidak akan berpura-pura "mandiri" hanya karena interpreter diganti bahasa implementasinya. Targetnya adalah **self-hosting bertahap**: program Qich tetap kompatibel sementara semakin banyak toolchain ditulis dalam Qich sendiri.

## Tahap

1. **Reference era (sekarang)** — implementasi referensi Python menjadi oracle perilaku. Fokus: spesifikasi, test konformansi, keamanan, portability.
2. **QVM era** — tetapkan bytecode Qich yang versioned dan VM kecil dengan format deterministik. Compiler referensi dapat menghasilkan QVM.
3. **Native bootstrap** — VM minimal dibawa ke implementasi low-level yang kecil dan auditable untuk bootstrap. Ini alat transisi, bukan identitas bahasa.
4. **Self-hosted compiler** — lexer, parser, semantic checker, optimizer, package resolver, dan compiler ditulis ulang dalam Qich, diverifikasi terhadap suite konformansi.
5. **Independent toolchain** — distribusi Qich membawa compiler/runtime sendiri. Python/JS/C bridge menjadi interoperability opsional, bukan syarat menjalankan program Qich.
6. **Multi-backend** — backend native/WASM/VM dapat berevolusi tanpa mengubah source language.

## Aturan migrasi

- Jangan hapus reference runtime sebelum penggantinya lulus suite konformansi.
- Artifact harus versioned, bounded, dan diverifikasi sebelum dieksekusi.
- Parser/compiler baru diuji differential terhadap implementasi referensi.
- Bridge asing default-deny untuk capability sensitif.
- Reproducible build dan signed release menjadi syarat sebelum klaim supply-chain hardened.
- Tidak ada klaim "lebih aman dari bahasa X" tanpa audit dan bukti terukur.

## Definisi "berdiri sendiri"

Qich disebut mandiri ketika compiler utama, runtime/VM, package tooling inti, dan standard library minimum dapat dibangun dan menjalankan suite Qich tanpa membutuhkan Python/Node sebagai runtime host. Toolchain awal tetap boleh memakai bootstrap seed, sebagaimana compiler modern pada umumnya memerlukan rantai bootstrap.
