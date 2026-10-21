#!/usr/bin/env python3
"""Package the Acode plugin as a ZIP with plugin.json and main.js at its root."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "dist" / "qich-acode-plugin.zip"
OUT.parent.mkdir(parents=True, exist_ok=True)

with ZipFile(OUT, "w", ZIP_DEFLATED) as archive:
    for name in ("plugin.json", "main.js", "readme.md"):
        archive.write(ROOT / name, arcname=name)

print(f"Plugin ZIP created: {OUT}")
