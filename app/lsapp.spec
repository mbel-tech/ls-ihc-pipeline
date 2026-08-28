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

# NOT collect_all("PySide6"). That drags in every Qt module built into the
# wheel - Qt3D, Charts, Quick3D, Multimedia, the lot - which made the build
# crawl through hooks for modules this app never imports. PyInstaller's own
# PySide6 hooks already collect what the imports below actually need, and
# QtWebEngine's resources come with them.

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
    # Qt modules nothing here imports. Named explicitly because PySide6's own
    # hooks are happy to pull siblings in, and each one costs tens of MB.
    excludes=[
        "tkinter", "matplotlib", "pytest",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
        "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
        "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
        "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSerialPort",
        "PySide6.QtDesigner", "PySide6.QtTest", "PySide6.QtSql",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSpatialAudio",
        "PySide6.QtScxml", "PySide6.QtSensors", "PySide6.QtWebSockets",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name="LS pipeline", console=False, icon=None)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name="LS pipeline")
