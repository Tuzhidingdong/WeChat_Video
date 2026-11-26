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
echo [DAILY TWO-VIDEO DISPATCHER]
echo 1. Literature reading: yesterday's published literature column.
echo 2. Science popularization: one unused human-approved Fact Card.
echo Pipelines execute sequentially under one shared production/upload lock.
echo Each result is reported independently; one failure does not suppress the other.
echo Only unpublished drafts are saved. No Publish/Schedule action exists.
echo.
".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli run-daily-two-videos
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
  echo.
  echo [OK] Daily dispatcher completed; review the per-pipeline results above.
) else (
  echo.
  echo [PARTIAL/BLOCKED] One or more pipelines failed or require reconciliation.
  echo No automatic upload retry was attempted.
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
