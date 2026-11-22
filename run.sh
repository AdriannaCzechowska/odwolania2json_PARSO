#!/usr/bin/env bash
# Uruchomienie CLI na Linuksie (Ubuntu). Uzycie: bash run.sh [argumenty main.py]
# Bez argumentow: input/ -> output/
set -e
cd "$(dirname "$0")"
export PYTHONUTF8=1
if [ ! -d .venv ]; then
  PY=""
  for c in python3.13 python3.14 python3; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
  if [ -z "$PY" ]; then echo "Brak Pythona 3.13+ (sudo apt install python3.13 python3.13-venv)"; exit 1; fi
  echo "Pierwsze uruchomienie: tworze srodowisko ($($PY --version)) i instaluje biblioteki..."
  "$PY" -m venv .venv || { echo "Brak modulu venv: sudo apt install ${PY}-venv"; exit 1; }
  .venv/bin/python -m pip install -q --upgrade pip
  .venv/bin/python -m pip install -q -r requirements.txt
fi
if [ ! -f .env ] && [ -z "$MISTRAL_API_KEY" ]; then
  echo "UWAGA: brak pliku .env i zmiennej MISTRAL_API_KEY - skopiuj .env.example jako .env"
fi
exec .venv/bin/python main.py "$@"
