<p align="center"><img src="logo/qich-logo.png" width="260" alt="Qich"></p>

# Qich

**Mudah · Aman · Cepat · Induk semua library** — AI · Web · Aplikasi.

> Satu bahasa, semua library — aman dan cepat. Dimulai bersama, berakhir mandiri.

Source `.qh` · artifact `.qhc` · CLI `qh`

## Pasang

Butuh Python ≥ 3.11 (Node.js opsional untuk `use js:`; g++ hanya untuk test C++).

```sh
sh install.sh                        # memasang ke ~/.local/bin/qh
export PATH="$HOME/.local/bin:$PATH"
qh --version
```

Alternatif: `pip install .` (entry point `qh`), atau tanpa memasang: `PYTHONPATH=src python3 -m qich ...`.

## Mulai

```sh
qh new my-app && cd my-app
qh run          # jalankan
qh test         # jalankan test_* di tests/ dan src/
qh build        # build/my-app.qhc  (artifact terverifikasi)
qh add <paket>  # dependensi (registry lokal / --path)
```

```
fn greet(name: str) -> str rtrn => f"Halo, {name}!"

fn main() {
    print(greet("dunia"))
}
```

Template showcase: `qh new x --template ai|web|app` (lihat `examples/`).

## Perintah

`new run build test add remove check fmt update doc clean` (wajib blueprint) + `bundle` (.pyz portabel), `publish`, `audit`, `bridges`, `repl`.

## Integrasi editor

- [Qich Language Support for Acode](integrations/acode/readme.md) — syntax highlighting `.qh`, tombol Run, dan eksekusi lewat terminal Acode (versi awal).

## Dokumen

- [docs/STATUS.md](docs/STATUS.md) — **apa yang IMPLEMENTED / TESTED / EXPERIMENTAL / PLANNED / UNAVAILABLE** (baca ini dulu)
- [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) — pemeriksaan sebelum rilis dan batasan yang masih diketahui
- [docs/LANGUAGE.md](docs/LANGUAGE.md) — referensi bahasa
- [docs/DECISIONS.md](docs/DECISIONS.md) — keputusan & resolusi konflik terhadap blueprint
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/BOOTSTRAP.md](docs/BOOTSTRAP.md), [docs/STDLIB.md](docs/STDLIB.md), [docs/BRIDGES.md](docs/BRIDGES.md)
- [security/SECURITY.md](security/SECURITY.md) — model ancaman & mekanisme
- [SECURITY.md](SECURITY.md) — kebijakan pelaporan kerentanan

## Menjalankan test

```sh
python3 -m unittest discover -s tests -p "test_*.py"   # 48 test Python (keamanan, bridge, paket, CLI, fuzz)
PYTHONPATH=src python3 -m qich test                     # 17 test .qh end-to-end
```
