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
echo Uploading the newest complete strict-QA-PASS video under standing draft-only authorization.
echo It will be saved as an UNPUBLISHED draft; the user alone publishes manually.
echo No per-video or Fact Card approval prompt is required. QA, account identity, duplicate protection and read-back verification remain mandatory.
echo It never clicks Publish, Send, Schedule, Delete or Overwrite.
".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli channels-upload-latest
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
  echo.
  echo [OK] A new unpublished draft was read back from the draft list.
) else (
  echo.
  echo [CHECK] Review the error and, for UPLOAD_UNKNOWN, run read-only reconciliation.
)

:finish
popd
if not defined RC set "RC=1"
echo.
pause
exit /b %RC%
