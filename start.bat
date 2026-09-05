@echo off
rem Starter golfturneringen lokalt og aabner browseren. Dobbeltklik paa filen.
rem Andre paa samme netvaerk kan bruge http://<din-ip>:8010 - skal alle kunne komme til fra internettet,
rem saa foelg README.md (server med Docker).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Det virtuelle miljoe mangler. Koer foerst: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)
start "" http://localhost:8010
".venv\Scripts\python.exe" -m uvicorn golf.server:app --host 0.0.0.0 --port 8010
pause
