@echo off
cd /d "%~dp0"
set PORT=8080
echo Starting Dashboard Piutang UP3 Makassar Selatan on http://localhost:%PORT%
python server.py --port %PORT%
pause
