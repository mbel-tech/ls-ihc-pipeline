@echo off
REM Build the bundled desktop app.
REM
REM Built with Python 3.13, not 3.14: pylibCZIrw publishes no cp314 wheel, and
REM the app runs its stages in-process, so the interpreter that freezes the app
REM is the one that has to be able to read CZIs. A 3.14 build works for
REM everything except the overview stage.
REM
REM The venv is created once and reused; delete work\appenv to start over.
setlocal
cd /d "%~dp0"

if not exist work\appenv\Scripts\python.exe (
  echo Creating the 3.13 build environment...
  py -3.13 -m venv work\appenv || goto :fail
  work\appenv\Scripts\python.exe -m pip install --upgrade pip || goto :fail
  work\appenv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-czi.txt || goto :fail
)

echo Building...
work\appenv\Scripts\pyinstaller.exe app\lsapp.spec --noconfirm || goto :fail

echo.
echo Built: dist\LS pipeline\LS pipeline.exe
echo Copy config.json in beside it, or let the first run ask for the paths.
goto :eof

:fail
echo.
echo BUILD FAILED - see the output above.
exit /b 1
