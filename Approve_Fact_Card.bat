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

echo.
echo One-time approval of the scientific Fact Card and its source record.
echo Read every claim, condition, caveat and cited source before confirming.
echo This does NOT approve a video, upload a video, or publish anything.
".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli approve-fact-card
set "RC=%ERRORLEVEL%"

:finish
popd
if not defined RC set "RC=1"
echo.
pause
exit /b %RC%
