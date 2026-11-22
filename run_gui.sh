#!/usr/bin/env bash
# Interfejs graficzny na Linuksie. Uzycie: bash run_gui.sh [port]
set -e
cd "$(dirname "$0")"
[ -d .venv ] || bash run.sh --help >/dev/null
export PYTHONUTF8=1
echo "GUI: http://localhost:${1:-8000} (Ctrl+C zatrzymuje serwer)"
exec .venv/bin/python server.py "${1:-8000}" --no-browser
