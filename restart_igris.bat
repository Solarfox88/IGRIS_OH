@echo off
echo Stopping old IGRIS process...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":7777"') do taskkill /F /PID %%a 2>nul
timeout /t 2 /nobreak >nul
echo Starting IGRIS...
cd /d C:\Igris\repo\IGRIS_DEVIN
call .venv\Scripts\activate.bat
start "igris-web" cmd /k "python -m igris web"
echo Done! IGRIS is restarting at http://127.0.0.1:7777
