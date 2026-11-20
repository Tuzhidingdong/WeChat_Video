@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PROJECT_ROOT=%~dp0"
pushd "%PROJECT_ROOT%"

set "TEMP=%PROJECT_ROOT%.cache\temp"
set "TMP=%PROJECT_ROOT%.cache\temp"
if not exist "%TEMP%" mkdir "%TEMP%"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Project environment not found. Run Setup_Slice_A.bat once first.
  set "RC=1"
  goto :finish
)

rem Project-local tool PATH from config/tools.local.json, current process only.
set "LOCAL_TOOL_PATH="
for /f "usebackq delims=" %%P in (`".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli tool-path`) do set "LOCAL_TOOL_PATH=%%P"
if defined LOCAL_TOOL_PATH set "PATH=%LOCAL_TOOL_PATH%;%PATH%"

echo [Slice A] Generating one local critical-nucleus review sample...
".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli run-slice-a --review-sample
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
  echo.
  echo [OK] Local review sample generated. Open REVIEW.md in the newest outputs folder.
  echo This candidate is NOT automatically uploaded or published.
) else (
  echo.
  echo [ERROR] Slice A did not complete. Read the reported failed stage and run.log.
)

:finish
popd
if not defined RC set "RC=1"
echo.
pause
exit /b %RC%
