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
echo Uploading the newest explicitly approved, QA-passed video as an UNPUBLISHED draft.
echo The uploader will verify the account and reconcile the draft list.
echo It will never click Publish or Send.
".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli channels-upload-latest
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
  echo.
  echo [OK] A new unpublished draft was read back from the draft list.
) else (
  echo.
  echo [CHECK] Review the error and, for UPLOAD_UNKNOWN, run the read-only reconciliation command.
)

:finish
popd
if not defined RC set "RC=1"
echo.
pause
exit /b %RC%
