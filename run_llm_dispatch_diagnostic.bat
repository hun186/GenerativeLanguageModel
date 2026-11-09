@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "scripts\diagnose_llm_dispatch_idle.py" %*
) else (
  python "scripts\diagnose_llm_dispatch_idle.py" %*
)
exit /b %ERRORLEVEL%
