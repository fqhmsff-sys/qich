# Library standar (ringkas)

Builtin: `print len str int float bool type repr abs min max sum round sorted range assert assert_eq panic Ok Err Error chan await_all exit input bytes`.
Metode `str`: `upper lower trim split starts ends contains find replace chars lines repeat pad`.
Metode `list`: `push pop map filter reduce each sort reversed contains index_of first last join extend insert remove_at any all enumerate zip sum min max copy find`.
Metode `map`: `keys values items get has remove merge clear copy`. `Result`: `is_ok is_err unwrap expect unwrap_or err map`.

`std:fs` read write append list mkdir remove remove_dir exists is_dir is_file join basename dirname ext · `std:json` parse stringify · `std:os` env secret args cwd run platform ·
`std:math` · `std:time` now monotonic sleep · `std:rand` Rng random int choice shuffle secure_bytes · `std:http` get post request (TLS wajib kecuali loopback).
`qy:model` Model Dense Tensor backends · `qy:lm` NgramLM · `qy:data` shuffle batches split normalize · `qy:tensor`.
`chyb:server` Server Response Request · `chyb:client` get post request. `qapp:ui` App Text Button Input Column Row State · `qapp:storage` Storage.
