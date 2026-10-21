@echo off
setlocal DisableDelayedExpansion
where py >nul 2>nul
if errorlevel 1 (
  python "%~dp0patch.py" setup
) else (
  py -3 "%~dp0patch.py" setup
)
set "bridge_exit=%errorlevel%"
pause
exit /b %bridge_exit%
