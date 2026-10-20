#!/usr/bin/env sh
# Instalasi Qich (bootstrap Python). Butuh Python >= 3.11. Node.js opsional (untuk adapter js:).
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"
"$PY" - <<'PYEOF' || { echo "Qich butuh Python >= 3.11" >&2; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)
PYEOF
BIN="${QH_PREFIX:-$HOME/.local}/bin"
LIB="${QH_PREFIX:-$HOME/.local}/lib/qich"
mkdir -p "$BIN" "$LIB"
rm -rf "$LIB/qich"
cp -R "$HERE/src/qich" "$LIB/qich"
find "$LIB" -name __pycache__ -type d -prune -exec rm -rf {} +
cat > "$BIN/qh" <<LAUNCH
#!/usr/bin/env sh
PYTHONPATH="$LIB\${PYTHONPATH:+:\$PYTHONPATH}" exec "$PY" -m qich "\$@"
LAUNCH
chmod +x "$BIN/qh"
echo "Qich terpasang: $BIN/qh"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "Tambahkan ke PATH:  export PATH=\"$BIN:\$PATH\"" ;; esac
"$BIN/qh" --version
