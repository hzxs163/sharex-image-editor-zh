@echo off
rem ============================================================
rem  Restore the untouched official ShareX.ImageEditor.dll
rem  (uses the .orig backup created by 应用汉化.bat, or original/)
rem ============================================================
setlocal
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY ( where py >nul 2>nul && set "PY=py" )
if not defined PY (
  echo [X] Python not found.
  pause
  exit /b 1
)
set "HERE=%~dp0"
set "TARGET=%~1"
if not "%TARGET%"=="" goto run
if exist "%HERE%ShareX.ImageEditor.dll" set "TARGET=%HERE%." & goto run
set /p "TARGET=Enter the ShareX folder: "
:run
%PY% "%HERE%apply_localization.py" "%TARGET%" --revert
echo.
pause
