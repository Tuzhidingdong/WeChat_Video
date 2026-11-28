@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PROJECT_ROOT=%~dp0"
pushd "%PROJECT_ROOT%"

rem This BAT must run the pipeline from THIS worktree, not an installed copy
rem of wechat_video from another workspace.
set "PYTHONPATH=%PROJECT_ROOT%src;%PYTHONPATH%"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Project environment not found. Run Setup_Slice_A.bat first.
  set "RC=1"
  goto :finish
)

set "LOCAL_TOOL_PATH="
for /f "usebackq delims=" %%P in (`".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli tool-path`) do set "LOCAL_TOOL_PATH=%%P"
if defined LOCAL_TOOL_PATH set "PATH=%LOCAL_TOOL_PATH%;%PATH%"

echo.
echo [LITERATURE MICRO VISUAL] Prepare content, optionally submit one Flow video,
echo then save one unpublished Channels draft. Publication is prohibited.
echo Account: 成核生长

set "STATE_FILE=%PROJECT_ROOT%runtime\micro_visual_last_status.json"
if exist "%STATE_FILE%" del /q "%STATE_FILE%" >nul 2>&1

".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli run-literature-micro-visual --state-file "%STATE_FILE%"
set "RC=%ERRORLEVEL%"

set "MSG="
set "STATE_MSG_FILE=%TEMP%\micro_visual_state_msg_%RANDOM%.txt"
if exist "%STATE_FILE%" (
  ".venv\Scripts\python.exe" -X utf8 -B -m wechat_video.micro_visual_status_readback "%STATE_FILE%" > "%STATE_MSG_FILE%" 2>nul
  if exist "%STATE_MSG_FILE%" set /p "MSG=" < "%STATE_MSG_FILE%"
)
if exist "%STATE_MSG_FILE%" del /q "%STATE_MSG_FILE%" >nul 2>&1

echo.
if defined MSG (
  echo %MSG%
) else (
  echo [STOP] 未能读取业务状态；不要将 exit code 视为草稿保存成功。
)
echo [INFO] 退出码 %RC% 仅供参考，成功与否以业务状态为准。
echo [INFO] state_file: %STATE_FILE%
echo [INFO] 报告目录：docs\reports\

:finish
popd
if not defined RC set "RC=1"
if /I not "%~1"=="--scheduled" (
  echo.
  pause
)
exit /b %RC%
