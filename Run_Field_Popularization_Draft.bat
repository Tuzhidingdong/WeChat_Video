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

set "LOCAL_TOOL_PATH="
for /f "usebackq delims=" %%P in (`".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli tool-path`) do set "LOCAL_TOOL_PATH=%%P"
if defined LOCAL_TOOL_PATH set "PATH=%LOCAL_TOOL_PATH%;%PATH%"

echo.
echo [SCIENCE POPULARIZATION] Select one unused, human-approved Fact Card.
echo Generate its script, render with the registered scientific visual strategy,
echo run strict QA, upload the exact output and verify one unpublished draft.
echo.
echo Account: 成核生长
echo Pending/review-sample Fact Cards are never eligible.
echo Publication is prohibited. Only an unpublished draft may be saved.
".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli run-popularization-daily
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
  echo.
  echo [OK] Popularization pipeline completed or safely skipped.
) else (
  echo.
  echo [STOP] Popularization pipeline failed or is blocked. No blind retry was attempted.
  echo Inspect runtime\daily_pipelines\jobs and runtime\upload_jobs.
)

:finish
popd
if not defined RC set "RC=1"
if /I not "%~1"=="--scheduled" (
  echo.
  pause
)
exit /b %RC%
