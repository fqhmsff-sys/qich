# Keamanan Qich — mekanisme dan buktinya

Setiap baris punya test (`tests/test_security.py`, `test_packages.py`, `test_chyb_cli.py`, `test_bridge.py`, `tests/qh/language_test.qh`).

| Area | Mekanisme | Test |
|---|---|---|
| Memori & batas | tanpa UB; indeks list/str/bytes dicek; hasil `*` dibatasi; rekursi & langkah dibatasi (`ResourceLimit`) | resource_limits, stack_overflow |
| Verifikasi artifact | `.qhc`: magic, SHA-256, whitelist node/field/tipe, batas kedalaman | qhc_*, corrupt_qhc_refused |
| Input salah/jahat | parser: batas nesting, tidak crash; fuzzing 400 mutasi program | fuzz_parser_and_runtime, parser_nesting_limit |
| FFI aman | `c:` hanya primitif/str, argumen divalidasi, `ffi.open` butuh izin | c_bridge_type_safety, cpp_extern_c |
| Bridge | denylist modul berbahaya, anggota privat diblokir, `js` di proses terpisah | bridge_denylist_and_allow, private_attr_blocked |
| Secret | `Secret` tercetak `***`, tak bisa JSON/bridge | secret_never_printed |
| Proses | `os.run` list-argumen tanpa shell, env disaring dari *KEY/TOKEN/SECRET/PASSWORD* | process_spawn_no_shell |
| Jaringan klien | skema dibatasi, HTTP non-loopback ditolak, redirect https→http ditolak, TLS verifikasi default, batas ukuran | http_client_defaults |
| Server `chyb` | bind 127.0.0.1, batas body, header keamanan, 500 tanpa detail, static anti-traversal, redirect/header injection diblokir, request malformed | tests chyb |
| Model tak tepercaya | JSON ter-skema (bukan pickle), validasi dimensi/finite/aktivasi/batas parameter | untrusted_model_rejected |
| Supply chain | checksum paket & arsip, `qh.lock` mengunci sumber (dependency confusion), nama cadangan, typosquatting, ekstraksi zip aman, tanpa install-script, `qh audit` memakai advisory registry | tests packages |

**Belum ada (jujur):** signed releases (PLANNED), isolasi proses untuk `py:` (in-process, bukan sandbox), batas memori proses, registry HTTPS/TUF, fuzzing berkelanjutan (hanya suite fuzz kecil), audit pihak ketiga.
**Melaporkan kerentanan:** buka advisory privat ke pengelola proyek; format advisory registry: `index.json → advisories → nama → [{id, summary, affected}]`.
