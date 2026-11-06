# Qich: jalur menuju toolchain mandiri

Qich tidak akan berpura-pura "mandiri" hanya karena interpreter diganti bahasa implementasinya. Targetnya adalah **self-hosting bertahap**: program Qich tetap kompatibel sementara semakin banyak toolchain ditulis dalam Qich sendiri.

## Tahap

1. **Reference era (sekarang)** — implementasi referensi Python menjadi oracle perilaku. Fokus: spesifikasi, test konformansi, keamanan, portability.
2. **QVM era** — tetapkan bytecode Qich yang versioned dan VM kecil dengan format deterministik. Compiler referensi dapat menghasilkan QVM.
3. **Native bootstrap** — VM minimal dibawa ke implementasi low-level yang kecil dan auditable untuk bootstrap. Ini alat transisi, bukan identitas bahasa.
4. **Self-hosted compiler** — lexer, parser, semantic checker, optimizer, package resolver, dan compiler ditulis ulang dalam Qich, diverifikasi terhadap suite konformansi.
5. **Independent toolchain** — distribusi Qich membawa compiler/runtime sendiri. Python/JS/C bridge menjadi interoperability opsional, bukan syarat menjalankan program Qich.
6. **Multi-backend** — backend native/WASM/VM dapat berevolusi tanpa mengubah source language.

## Status implementasi

- QVM1 sudah memiliki envelope bytecode versioned, deterministik, checksum, validasi opcode/operand, dan batas resource. Verifier menganalisis tinggi stack pada semua jalur control-flow yang reachable, menolak underflow statis, join dengan tinggi stack berbeda, loop yang menumbuhkan stack, serta stack statis di atas batas executor. Decoder menolak duplicate JSON keys, invalid Unicode, float non-finite, integer terlalu besar, serta nesting JSON berlebihan tanpa membocorkan RecursionError.
- Reference stack executor QVM1 sudah tersedia untuk mengunci semantik ISA dasar dan memiliki step/stack budget. Executor ini masih Python dan karena itu **belum** memenuhi milestone native bootstrap.
- Compiler subset Qich AST -> QVM1 mendukung literal, unary dasar, arithmetic/comparison, ternary, short-circuit `&&`/`||`, expression statements, serta local state (`let`, lookup, assignment sederhana). Anotasi tipe dan syntax lain yang belum dikonformansikan ditolak tertutup.
- QVM reference executor memvalidasi boolean secara ketat, menyamakan equality dengan aturan Qich (bool tidak disamakan dengan angka), membatasi ukuran integer/string, dan menolak float non-finite.
- Differential corpus membandingkan arithmetic, comparison, equality, string repetition, ternary, short-circuit, dan local state dengan evaluator referensi.
- Langkah berikutnya: perluas differential/error conformance, lalu implementasikan native bootstrap VM kecil tanpa Python/Node. Compiler dan executor saat ini masih komponen referensi Python, bukan self-hosting.
- Jangan memperluas ISA hanya untuk mengejar jumlah opcode; tambah primitive ketika dibutuhkan oleh compiler dan dapat diuji konformansinya.

## Aturan migrasi

- Jangan hapus reference runtime sebelum penggantinya lulus suite konformansi.
- Artifact harus versioned, bounded, dan diverifikasi sebelum dieksekusi.
- Parser/compiler baru diuji differential terhadap implementasi referensi.
- Bridge asing default-deny untuk capability sensitif.
- Reproducible build dan signed release menjadi syarat sebelum klaim supply-chain hardened.
- Tidak ada klaim "lebih aman dari bahasa X" tanpa audit dan bukti terukur.

## Definisi "berdiri sendiri"

Qich disebut mandiri ketika compiler utama, runtime/VM, package tooling inti, dan standard library minimum dapat dibangun dan menjalankan suite Qich tanpa membutuhkan Python/Node sebagai runtime host. Toolchain awal tetap boleh memakai bootstrap seed, sebagaimana compiler modern pada umumnya memerlukan rantai bootstrap.
