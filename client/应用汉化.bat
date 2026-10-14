@echo off
rem ============================================================
rem  Apply Chinese localization to the ShareX image editor.
rem  Close ShareX first (tray icon -> Exit).
rem  Works when this file sits inside the ShareX folder, next to
rem  it, or when you pass the folder as the first argument.
rem ============================================================
setlocal
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY ( where py >nul 2>nul && set "PY=py" )
if not defined PY (
  echo [X] Python not found. Install Python 3, then run this again.
  pause
  exit /b 1
)

set "HERE=%~dp0"
set "TARGET=%~1"

if not "%TARGET%"=="" goto run
if exist "%HERE%ShareX.ImageEditor.dll" set "TARGET=%HERE%." & goto run
%PY% "%HERE%apply_localization.py" --detect
set /p "TARGET=Enter the ShareX folder (or press Enter to auto-detect): "
if "%TARGET%"=="" set "TARGET=%HERE%.."

:run
%PY% "%HERE%apply_localization.py" "%TARGET%"
echo.
pause
