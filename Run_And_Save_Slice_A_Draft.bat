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

rem Resolve project-local FFmpeg/LaTeX paths for this process only.
set "LOCAL_TOOL_PATH="
for /f "usebackq delims=" %%P in (`".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli tool-path`) do set "LOCAL_TOOL_PATH=%%P"
if defined LOCAL_TOOL_PATH set "PATH=%LOCAL_TOOL_PATH%;%PATH%"

echo.
echo [ONE CLICK] Generate the current Slice A review sample, run strict QA,
echo upload exactly that MP4 to the 「成核生长」 account, save as an unpublished draft,
echo then read the draft list back to verify the new entry.
echo.
echo Standing authorization covers draft-only upload. Strict QA and account checks remain mandatory.
echo The workflow never publishes, sends, schedules, deletes or overwrites.
".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli run-slice-a-and-upload-draft
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
  echo.
  echo [OK] The generated video was read back as an unpublished Channels draft.
  echo Check the draft in WeChat on your phone. Phone-side visibility is not verified by this PC workflow.
  echo Final publication remains manual; no publish action was taken.
) else (
  echo.
  echo [STOP] The workflow failed or was blocked. No automatic retry was attempted.
  echo Read the error above and inspect the matching outputs/run.log and runtime/upload_jobs record.
)

:finish
popd
if not defined RC set "RC=1"
echo.
pause
exit /b %RC%
