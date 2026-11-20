@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PROJECT_ROOT=%~dp0"
pushd "%PROJECT_ROOT%"

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
  echo Install a supported 64-bit Python release, then retry.
  set "RC=1"
  goto :finish
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,13) else 1)" >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Existing .venv uses an unsupported Python. Rename or remove this project-local .venv, then retry.
    set "RC=1"
    goto :finish
  )
) else (
  echo [1/4] Creating an isolated project .venv...
  %PY_BOOT% -m venv ".venv"
  if errorlevel 1 (
    set "RC=1"
    goto :finish
  )
)
".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,13) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Slice A requires Python 3.11 or 3.12. Python 3.13 is not supported by the selected Windows TTS wheel.
  set "RC=1"
  goto :finish
)

echo [2/4] Installing Slice A dependencies into .venv...
".venv\Scripts\python.exe" -X utf8 -m pip install --disable-pip-version-check --no-input -r "requirements-slice-a.txt"
if errorlevel 1 (
  echo [ERROR] Dependency installation failed. Global Python was not modified.
  set "RC=1"
  goto :finish
)
".venv\Scripts\python.exe" -X utf8 -m pip install --disable-pip-version-check --no-input -e .
if errorlevel 1 (
  echo [ERROR] Could not install this project into its local .venv.
  set "RC=1"
  goto :finish
)

echo [3/4] Downloading the official sherpa-onnx Chinese/English ONNX model once...
".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli download-model
if errorlevel 1 (
  echo [ERROR] Offline TTS model setup failed.
  set "RC=1"
  goto :finish
)

echo [4/4] Running environment preflight...
".venv\Scripts\python.exe" -X utf8 -m wechat_video.cli preflight
if errorlevel 1 (
  echo [ERROR] Environment preflight did not pass. Review the diagnostics above.
  set "RC=1"
  goto :finish
)

echo.
echo [OK] Slice A project environment is ready.
echo Next: double-click Run_Slice_A.bat to generate the candidate review sample.
set "RC=0"

:finish
popd
if not defined RC set "RC=1"
echo.
if not "%RC%"=="0" echo Setup failed. See the message above.
pause
exit /b %RC%
