# Arsitektur

```
.qh ──lexer──▶ tokens ──parser──▶ AST ──semantic──▶ diagnostik
                                   │
                                   ├─ qhc.dump ─▶ .qhc (IR + sha256)   ─ qhc.load (verifier) ─┐
                                   ▼                                                          ▼
                              Interp (runtime) ◀── Loader (FileSource | BundleSource) ◀─────────┘
                                   │
        ┌──────────────┬───────────┼────────────────┬─────────────────────┐
     builtins       std/*     qy · chyb · qapp     bridge (py · js · c · cpp · …registry)
```

- `src/qich/compiler` lexer, parser, ast, semantic, fmt, doc, qhc, diagnostics
- `src/qich/runtime` values, interp, builtins, loader, stdlib (registry modul)
- `src/qich/std` fs, json, os, math, time, rand, http
- `src/qich/qy|chyb|qapp` library resmi (API stabil, backend dapat diganti)
- `src/qich/bridge` Universal Bridge Layer: registry adapter + capability yang dapat dideteksi (`qh bridges`)
- `src/qich/package` manifest, lock, registry, resolver
- `src/qich/security` kebijakan bridge, ekstraksi arsip aman
- `src/qich/cli` perintah `qh`

**Backend selection**: API Qich (mis. `Model.load`) tidak berubah ketika backend berubah; `qy.backends()` melaporkan backend dan statusnya. Migrasi final mengganti implementasi host Python pada compiler, runtime, package tooling, dan minimum stdlib dengan implementasi Qich-native. C/Rust hanya boleh menjadi bootstrap seed build-time yang sementara, bukan runtime permanen.

## Arsitektur target mandiri

```
.qh ─▶ Qich-native compiler ─▶ QVM/native artifact
             │                         │
             ▼                         ▼
      Qich package tooling      Qich-native runtime/VM
             │                         │
             └──────── Qich stdlib ────┘
                         │
                 OS / hardware ABI
```

Source compiler, VM/runtime, package tooling, dan minimum stdlib yang menjadi produk akhir harus ditulis dan dipelihara dalam Qich. Bootstrap seed hanya membangun generasi awal; setelah rantai bootstrap berhasil, seed tidak boleh menjadi runtime host wajib. Python/JavaScript/C dan bahasa lain hanya adapter interoperabilitas opsional. Tenggat final untuk memenuhi gerbang kemandirian adalah **14 Desember 2026**.
