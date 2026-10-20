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

**Backend selection**: API Qich (mis. `Model.load`) tidak berubah ketika backend berubah; `qy.backends()` melaporkan backend dan statusnya. **Migrasi ke mandiri**: tiap modul native Python di `std/qy/chyb/qapp` adalah titik penggantian oleh implementasi Qich-native/Rust.
