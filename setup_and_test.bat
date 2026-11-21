@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist .venv (
  echo Tworze srodowisko Python i instaluje biblioteki, to potrwa 1-2 minuty...
  py -3.13 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat
python --version
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
echo.
echo === Test polaczenia z Mistral ===
python smoke_test.py
echo.
pause
