@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    python run.py %*
) else (
    py -3 run.py %*
)
set "resultado=%errorlevel%"
pause
exit /b %resultado%
