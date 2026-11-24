@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PROJECT_ROOT=%~dp0"
pushd "%PROJECT_ROOT%"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Project environment not found. Run Setup_Slice_A.bat first.
  set "RC=1"
  goto :finish
)

".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli channels-session
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
  echo.
  echo [OK] Dedicated Edge is open. If requested, sign in by QR code.
  echo This command does not upload or save any video.
)

:finish
popd
if not defined RC set "RC=1"
echo.
pause
exit /b %RC%
