@echo off
setlocal
cd /d "%~dp0"
if not defined USERPROFILE (
  echo REVIEW_REQUIRED: USERPROFILE_UNAVAILABLE
  exit /b 2
)
set "PROBE_PY=python"
if exist ".venv\Scripts\python.exe" set "PROBE_PY=%CD%\.venv\Scripts\python.exe"
"%PROBE_PY%" "scripts\verify_windows_queue_ntfs_local.py" --output-dir "%USERPROFILE%\queue-ntfs-acceptance-results"
set "PROBE_RC=%ERRORLEVEL%"
if not "%PROBE_RC%"=="0" (
  echo REVIEW_REQUIRED: inspect JSON in %%USERPROFILE%%\queue-ntfs-acceptance-results
) else (
  echo FIXTURE_PASS_ONLY: deployment and live queues remain UNVERIFIED
  echo Report folder: %%USERPROFILE%%\queue-ntfs-acceptance-results
)
exit /b %PROBE_RC%
