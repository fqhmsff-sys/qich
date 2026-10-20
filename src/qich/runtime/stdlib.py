"""Registry library standar & Qichy (std, qy, chyb, qapp)."""
ECOS = ("std", "qy", "chyb", "qapp")


def _table():
    from ..std import core
    from .. import qy, chyb, qapp
    return {"std": core.MODULES, "qy": qy.MODULES, "chyb": chyb.MODULES, "qapp": qapp.MODULES}


def available(eco):
    return list(_table()[eco])


def load(eco, lib, I):
    from ..compiler.diagnostics import QichError
    mods = _table()[eco]
    if lib not in mods:
        raise QichError(f"modul '{eco}:{lib}' tidak ada", "ImportError", "R0120",
                        "tersedia: " + ", ".join(sorted(mods)))
    return mods[lib](I), eco != "std"


def exports_of(eco, lib):
    mods = _table().get(eco, {})
    if lib not in mods:
        return None
    try:
        return mods[lib](None)
    except Exception:
        return {}
