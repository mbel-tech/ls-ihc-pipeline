@echo off
REM Rebuild both ROI datasets and re-plot every hour until detection finishes.
REM
REM Uses work\appenv, not the Python on PATH: openpyxl and pylibCZIrw live in
REM the venv, and the bare interpreter has neither.
REM
REM Runs until 05c_detect_rois.py has measured every section, then does a final
REM rebuild and exits. Ctrl+C is safe - nothing is left half written.
cd /d "%~dp0"
work\appenv\Scripts\python.exe scripts\06e_refresh_loop.py %*
if errorlevel 1 pause
