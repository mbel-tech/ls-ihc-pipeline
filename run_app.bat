@echo off
REM Launch the pipeline app.
REM
REM Prefers work\appenv - the SAME Python 3.13 venv build_app.bat freezes the
REM exe from, and the one refresh_loop.bat already uses. The Python on PATH here
REM is 3.14, which has no PySide6 wheel installed and cannot import pylibCZIrw
REM at all, so `python -m app` failed with ModuleNotFoundError: PySide6 and
REM wrote a traceback to lsapp-crash.log. Falling back to PATH keeps this
REM working on a machine that installed the requirements globally instead.
cd /d "%~dp0"

if exist "work\appenv\Scripts\python.exe" (
  work\appenv\Scripts\python.exe -m app %*
) else (
  echo work\appenv not found - falling back to the Python on PATH.
  echo If this fails with "No module named PySide6", either run build_app.bat
  echo to create the venv, or: pip install -r requirements.txt
  python -m app %*
)

if errorlevel 1 pause
