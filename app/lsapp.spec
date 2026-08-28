# PyInstaller spec for the pipeline app.
#
#   pyinstaller app/lsapp.spec --noconfirm
#
# ONE-FOLDER, not one-file. QtWebEngine runs a separate helper process
# (QtWebEngineProcess.exe) that has to find its resources and locales on disk;
# a one-file build unpacks to a temp directory the helper does not inherit, and
# the curator panes come up blank with no error worth reading.
#
# Build with the interpreter the app is meant to run on. pylibCZIrw ships no
# cp314 wheel, so a 3.14 build cannot include it and the overview stage will be
# missing from the bundle - see README.
#
# scripts/ is shipped as DATA, not as imports: the runner loads stages by file
# path, which is what lets them keep their numeric names.

import os
from PyInstaller.utils.hooks import collect_all

REPO = os.path.abspath(os.path.join(os.getcwd()))

datas = [
    (os.path.join(REPO, "scripts"), "scripts"),
    (os.path.join(REPO, "config.example.json"), "."),
]
binaries, hiddenimports = [], []
for pkg in ("PySide6",):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# pylibCZIrw carries a compiled extension and data files it will not find on its
# own. Absent (a 3.14 build) this is simply skipped rather than failing here.
try:
    d, b, h = collect_all("pylibCZIrw")
    datas += d; binaries += b; hiddenimports += h
except Exception:
    pass

a = Analysis(
    [os.path.join(REPO, "app", "__main__.py")],
    pathex=[os.path.join(REPO, "app")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + [
        "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore",
        "PySide6.QtWebChannel", "PySide6.QtNetwork", "PySide6.QtPrintSupport",
    ],
    excludes=["tkinter", "matplotlib", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name="LS pipeline", console=False, icon=None)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name="LS pipeline")
