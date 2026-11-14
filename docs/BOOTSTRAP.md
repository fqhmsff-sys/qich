# Qich: jalur menuju toolchain mandiri

Qich tidak akan berpura-pura "mandiri" hanya karena interpreter diganti bahasa implementasinya. Targetnya adalah **self-hosting bertahap**: program Qich tetap kompatibel sementara semakin banyak toolchain ditulis dalam Qich sendiri.

## Tahap

1. **Reference era (sekarang)** — implementasi referensi Python menjadi oracle perilaku dan alat differential testing. Python bukan arsitektur runtime final.
2. **QVM era** — tetapkan bytecode Qich yang versioned dan VM referensi kecil dengan format deterministik. Compiler referensi dapat menghasilkan QVM.
3. **Bootstrap seed sementara** — sebuah seed kecil dan auditable boleh dipakai untuk membangun generasi native pertama. Seed hanya alat build-time; bukan runtime host yang dibawa atau diwajibkan oleh distribusi akhir.
4. **Qich-native core** — implementasikan VM/runtime, compiler, dan primitive sistem inti dalam Qich. Seed mengompilasi generasi pertama; implementasi Qich kemudian mengambil alih pembangunan dan eksekusi.
5. **Self-hosted compiler** — lexer, parser, semantic checker, optimizer, package resolver, dan compiler ditulis dalam Qich. Uji rantai stage0 → stage1 → stage2 dan konformansi semantik.
6. **Independent toolchain** — compiler utama, runtime/VM, package tooling inti, dan minimum standard library dibangun/dijalankan tanpa Python atau Node sebagai runtime host wajib.
7. **Multi-backend** — backend native/WASM/VM dapat berevolusi tanpa mengubah source language. Bridge C, Python, JavaScript, dan bahasa lain tetap opsional.

## Status implementasi

- QVM1 sudah memiliki envelope bytecode versioned, deterministik, checksum, validasi opcode/operand, dan batas resource. Verifier menganalisis tinggi stack pada semua jalur control-flow yang reachable, menolak underflow statis, join dengan tinggi stack berbeda, loop yang menumbuhkan stack, serta stack statis di atas batas executor. Decoder menolak duplicate JSON keys, invalid Unicode, float non-finite, integer terlalu besar, serta nesting JSON berlebihan tanpa membocorkan RecursionError.
- Reference stack executor QVM1 sudah tersedia untuk mengunci semantik ISA dasar dan memiliki step/stack budget. Eksekusi one-shot menyalin program ke snapshot sebelum verifikasi agar mutasi caller setelah validasi tidak mengubah bytecode yang dijalankan; `prepare()` menyediakan snapshot immutable yang dapat dipakai ulang. Executor ini masih Python dan karena itu **belum** memenuhi milestone native bootstrap.
- Compiler subset Qich AST -> QVM1 mendukung literal, unary dasar, arithmetic/comparison, ternary, short-circuit `&&`/`||`, expression statements, serta local state (`let`, lookup, assignment sederhana). Anotasi tipe dan syntax lain yang belum dikonformansikan ditolak tertutup.
- QVM reference executor memvalidasi boolean secara ketat, menyamakan equality dengan aturan Qich (bool tidak disamakan dengan angka), membatasi ukuran integer/string, dan menolak float non-finite.
- Source bootstrap menggunakan `int.bit_length()` untuk menerapkan batas integer tepat 13.000 bit yang sama dengan reference verifier; runtime native nantinya wajib mempertahankan semantik primitive ini.
- Differential corpus membandingkan arithmetic, comparison, equality, string repetition, ternary, short-circuit, dan local state dengan evaluator referensi.
- `bootstrap/qvm1.qh` kini memuat prototype verifier/executor QVM1 yang ditulis dalam Qich dan diuji melalui Python reference runtime. Ini source Qich, tetapi belum executable native, belum membaca envelope/checksum bytecode, dan belum menggantikan reference VM.
- Langkah berikutnya: porting source prototype ini ke subset QVM yang dapat dikompilasi, perluas differential/error conformance, lalu bangun bootstrap seed/native VM. Compiler dan executor QVM1 production saat ini masih komponen referensi Python, bukan self-hosting.
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


## Tenggat final dan gerbang penerimaan

**14 Desember 2026 adalah tenggat final kemandirian Qich.** Ini kriteria penerimaan, bukan alasan untuk menghapus pengujian atau menyebut pekerjaan selesai sebelum terbukti.

Qich hanya boleh dinyatakan mandiri setelah seluruh gerbang berikut lulus:

- Lingkungan clean-room dapat membangun dan menjalankan compiler, runtime/VM, package tooling inti, serta minimum stdlib tanpa Python/Node terpasang.
- Source compiler dan runtime inti yang dipelihara untuk distribusi akhir adalah source Qich; bootstrap seed hanya diperlukan untuk membangun generasi awal dan tidak menjadi runtime wajib.
- Compiler stage1 dapat membangun compiler stage2 dari source Qich; hasil build dan perilakunya dibandingkan secara reproducible.
- Bytecode/QVM conformance dan differential corpus lulus pada reference implementation serta runtime native.
- Package install/build dan program standar dapat dijalankan dari lingkungan bersih tanpa memanggil Python/Node.
- Regression, security, resource-limit, portability, dan performance tests lulus pada platform yang dinyatakan didukung.
- Bridge bahasa lain tidak diperlukan untuk menjalankan program inti Qich.

Selama migrasi, Python reference implementation tetap dipakai sebagai oracle pengujian. C/Rust atau toolchain lain boleh menjadi bootstrap seed build-time bila diperlukan, tetapi tidak boleh menjadi lapisan runtime permanen atau identitas implementasi akhir Qich.
