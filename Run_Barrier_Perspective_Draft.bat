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
echo [EDITORIAL VARIANT] free_energy_barrier_perspective
echo Fact Card: critical_nucleus_barrier_perspective.json
echo Script:    barrier_perspective_script.en.json
echo The matching script is passed explicitly; no silent fallback to the old sample script.
echo.

".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli run-slice-a-and-upload-draft --fact-card "fact_cards\critical_nucleus_barrier_perspective.json" --script "content\barrier_perspective_script.en.json"
set "RC=%ERRORLEVEL%"

:finish
popd
if not defined RC set "RC=1"
echo.
pause
exit /b %RC%
