@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PROJECT_ROOT=%~dp0"
pushd "%PROJECT_ROOT%"

rem All caches and temporary files stay inside this project.
set "PIP_CACHE_DIR=%PROJECT_ROOT%.cache\pip"
set "TEMP=%PROJECT_ROOT%.cache\temp"
set "TMP=%PROJECT_ROOT%.cache\temp"
for %%D in ("%PIP_CACHE_DIR%" "%TEMP%") do if not exist %%D mkdir %%D

set "PY_BOOT="
where py >nul 2>nul
if not errorlevel 1 (
  py -3.12 --version >nul 2>nul
  if not errorlevel 1 set "PY_BOOT=py -3.12"
  if not defined PY_BOOT (
    py -3.11 --version >nul 2>nul
    if not errorlevel 1 set "PY_BOOT=py -3.11"
  )
)
if not defined PY_BOOT (
  python --version >nul 2>nul
  if not errorlevel 1 set "PY_BOOT=python"
)
if not defined PY_BOOT (
  echo [ERROR] Python 3.11 or 3.12 was not found.
  set "RC=1"
  goto :finish
)

if exist ".venv\Scripts\python.exe" (
  echo [1/4] Reusing existing project .venv.
) else (
  echo [1/4] Creating an isolated project .venv...
  %PY_BOOT% -m venv ".venv"
  if errorlevel 1 (
    echo [ERROR] Could not create the project .venv.
    set "RC=1"
    goto :finish
  )
)
".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,13) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Slice A requires Python 3.11 or 3.12.
  set "RC=1"
  goto :finish
)

".venv\Scripts\python.exe" -X utf8 -c "import manim, sherpa_onnx, soundfile, pytest" >nul 2>nul
if errorlevel 1 (
  echo [2/4] Installing missing Python dependencies into .venv...
  ".venv\Scripts\python.exe" -X utf8 -m pip install --disable-pip-version-check --no-input -r "requirements-slice-a.txt" pytest
  if errorlevel 1 (
    echo [ERROR] Dependency installation failed. Global Python was not modified.
    set "RC=1"
    goto :finish
  )
  ".venv\Scripts\python.exe" -X utf8 -m pip install --disable-pip-version-check --no-input --no-deps -e .
  if errorlevel 1 (
    echo [ERROR] Could not install this project into its local .venv.
    set "RC=1"
    goto :finish
  )
) else (
  echo [2/4] Python dependencies already present in .venv.
)

rem Project-local tool PATH from config/tools.local.json, current process only.
set "LOCAL_TOOL_PATH="
for /f "usebackq delims=" %%P in (`".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli tool-path`) do set "LOCAL_TOOL_PATH=%%P"
if defined LOCAL_TOOL_PATH set "PATH=%LOCAL_TOOL_PATH%;%PATH%"

if not exist "tools\ffmpeg\bin\ffmpeg.exe" (
  echo [ERROR] Project FFmpeg is missing: tools\ffmpeg\bin\ffmpeg.exe
  set "RC=1"
  goto :finish
)
if not exist "tools\ffmpeg\bin\ffprobe.exe" (
  echo [ERROR] Project ffprobe is missing: tools\ffmpeg\bin\ffprobe.exe
  set "RC=1"
  goto :finish
)
if not exist "tools\miktex-portable\texmfs\install\miktex\bin\x64\latex.exe" (
  echo [ERROR] Project MiKTeX Portable is missing.
  set "RC=1"
  goto :finish
)
if not exist "tools\miktex-portable\texmfs\install\miktex\bin\x64\dvisvgm.exe" (
  echo [ERROR] Project dvisvgm is missing.
  set "RC=1"
  goto :finish
)

".venv\Scripts\python.exe" -X utf8 -c "from wechat_video.model_setup import _model_dir_valid; from wechat_video.tooling import model_root; import sys; sys.exit(0 if _model_dir_valid(model_root()) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [3/4] Downloading the offline TTS model once...
  ".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli download-model
  if errorlevel 1 (
    echo [ERROR] Offline TTS model setup failed.
    set "RC=1"
    goto :finish
  )
) else (
  echo [3/4] Offline TTS model already present.
)

echo [4/4] Running project-local environment preflight...
".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli preflight
if errorlevel 1 (
  echo [ERROR] Environment preflight did not pass.
  set "RC=1"
  goto :finish
)

echo.
echo [OK] Slice A project environment is ready. No global configuration was changed.
set "RC=0"

:finish
popd
if not defined RC set "RC=1"
echo.
if not "%RC%"=="0" echo Setup failed. See the message above.
pause
exit /b %RC%
