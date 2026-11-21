@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist .venv (
  echo Pierwsze uruchomienie: tworze srodowisko i instaluje biblioteki...
  py -3.13 -m venv .venv || python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install -q -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
echo Otwieram http://localhost:8000 (zamknij to okno, aby zatrzymac serwer)
python server.py
