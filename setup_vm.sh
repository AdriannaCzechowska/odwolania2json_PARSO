#!/usr/bin/env bash
# Jednorazowa instalacja na serwerze oceny (Ubuntu 24.04), w katalogu /opt/solution.
# Uzycie: bash setup_vm.sh          (instalacja)
#         bash setup_vm.sh --gui    (instalacja + GUI na porcie 8000 startujace samo po restarcie)
set -e
cd "$(dirname "$0")"
SOL="$(pwd)"

if ! command -v python3.13 >/dev/null 2>&1; then
  echo "== Instaluje Python 3.13 (deadsnakes)..."
  ( sudo add-apt-repository -y ppa:deadsnakes/ppa && sudo apt-get update -q \
    && sudo apt-get install -y -q python3.13 python3.13-venv ) \
    || echo "!! Nie udalo sie zainstalowac 3.13 - uzyje python3 ($(python3 --version))"
fi
PY="$(command -v python3.13 || command -v python3)"

echo "== Srodowisko: $($PY --version)"
rm -rf .venv
"$PY" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt
.venv/bin/python -c "import pymupdf, openai, jsonschema, yaml, fastapi, PIL; print('== Biblioteki OK')"

mkdir -p input output
if [ ! -f .env ]; then
  cp .env.example .env
  echo "!! Uzupelnij klucz API: nano $SOL/.env"
fi

if [ "$1" = "--gui" ]; then
  sudo tee /etc/systemd/system/parso-gui.service >/dev/null <<UNIT
[Unit]
Description=PARSO GUI (Odwolania2JSON)
After=network-online.target

[Service]
WorkingDirectory=$SOL
ExecStart=$SOL/.venv/bin/python server.py 8000 --public
Restart=always
User=$(id -un)

[Install]
WantedBy=multi-user.target
UNIT
  sudo systemctl daemon-reload
  sudo systemctl enable --now parso-gui
  echo "== GUI: http://$(curl -s -4 ifconfig.me || hostname -I | cut -d' ' -f1):8000"
fi
echo "== Gotowe. Test jak u oceniajacych: sudo bash run.sh"
