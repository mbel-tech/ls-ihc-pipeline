@echo off
REM Launch the pipeline app. Uses the Python on PATH; see README for the
REM version requirement (pylibCZIrw needs <= 3.13 for the overview stage).
cd /d "%~dp0"
python -m app
if errorlevel 1 pause
