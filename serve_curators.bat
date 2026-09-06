@echo off
REM Serve the curator pages over http and open one in a browser.
REM
REM A page opened by double-clicking it is file://, and a file:// page cannot
REM read its own images back - so the Shotgun deck disables itself there. Served
REM over http a browser is on equal terms with the app.
REM
REM Uses work\appenv when it exists, like refresh_loop.bat; nothing here needs
REM PySide6, so the Python on PATH is fine too.
cd /d "%~dp0"
if exist "work\appenv\Scripts\python.exe" (
  work\appenv\Scripts\python.exe scripts\serve_curators.py %*
) else (
  python scripts\serve_curators.py %*
)
if errorlevel 1 pause
