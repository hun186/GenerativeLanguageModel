@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 (
  echo Cannot open project directory.
  pause
  exit /b 2
)
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
if exist ".venv\Scripts\python.exe" (
  set "DIAG_PY=.venv\Scripts\python.exe"
) else (
  set "DIAG_PY=python"
)
if not "%~1"=="" goto :ARGS
echo.
echo ========== LLM / GPU Dispatch Diagnostic ==========
echo Read-only, local evidence only.
echo.
"%DIAG_PY%" "scripts\diagnose_llm_dispatch_idle.py" --human
set "DIAG_EXIT=%errorlevel%"
echo.
echo 按任意鍵關閉此視窗。
pause >nul
exit /b %DIAG_EXIT%
:ARGS
"%DIAG_PY%" "scripts\diagnose_llm_dispatch_idle.py" %*
exit /b %errorlevel%
