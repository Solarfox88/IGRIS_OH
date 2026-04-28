@echo off
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":7777"') do (
    taskkill /F /PID %%a 2>nul
)
timeout /t 1 /nobreak >nul
cd /d C:\Igris\repo\IGRIS_DEVIN
call .venv\Scripts\activate.bat
start "" /B cmd /c "python -m igris web > igris_run.log 2>&1"
timeout /t 3 /nobreak >nul
echo DONE
