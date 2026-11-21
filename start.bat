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
if not exist .env echo UWAGA: brak pliku .env z kluczem API - skopiuj .env.example jako .env
python main.py %*
pause
