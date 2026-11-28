@echo off
setlocal
set "JOBPILOT_PYTHON="
for /f "delims=" %%P in ('py -3.13 -c "import sys; print(sys.executable)" 2^>nul') do set "JOBPILOT_PYTHON=%%P"
if not defined JOBPILOT_PYTHON (
  echo Install 64-bit Python 3.13 with the Python launcher, then open this installer again.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Install-JobPilot.ps1" -Python "%JOBPILOT_PYTHON%" -Launch
if errorlevel 1 (
  echo The update did not complete. See the message above.
  pause
  exit /b 1
)
