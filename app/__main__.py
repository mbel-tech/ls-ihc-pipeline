"""Entry point: `python -m app` from the repo root, or run_app.bat / the .exe.

Two things this file exists to get right.

**Where the repo is.** Running from source, it is the folder above this one.
Frozen, `__file__` points inside the bundle, so the repo would resolve to a
directory inside `_internal` and config.json would never be found. Frozen builds
therefore take the folder holding the .exe as the place config lives - which is
also where the user can see and edit it - while the stage scripts come from the
bundle.

**Saying so when it dies.** A windowed PyInstaller build has no console: an
unhandled exception kills it with no message, no dialog, and no exit code worth
reading. Anything that escapes is written to a crash log beside the executable
and shown in a message box, because "it just closes" is not something anyone can
act on.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    REPO = os.path.dirname(os.path.abspath(sys.executable))
    SCRIPTS = os.path.join(getattr(sys, "_MEIPASS", HERE), "scripts")
else:
    REPO = os.path.dirname(HERE)
    SCRIPTS = os.path.join(REPO, "scripts")

if HERE not in sys.path:
    sys.path.insert(0, HERE)

CRASH_LOG = os.path.join(REPO, "lsapp-crash.log")


def _report(exc_type, exc, tb):
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        with open(CRASH_LOG, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        pass
    sys.stderr.write(text)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance():
            QMessageBox.critical(
                None, "LS pipeline stopped",
                f"{exc_type.__name__}: {exc}\n\nWritten to:\n{CRASH_LOG}")
    except Exception:                                       # noqa: BLE001
        pass


def main():
    sys.excepthook = _report
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as e:
        _report(type(e), e, e.__traceback__)
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("LS IHC pipeline")

    try:
        from config_dialog import ensure_config
        if not ensure_config(REPO):
            return 0                       # the user cancelled setup

        from main_window import MainWindow
        w = MainWindow(REPO, scripts_dir=SCRIPTS)
        w.show()
        return app.exec()
    except BaseException as e:                              # noqa: BLE001
        _report(type(e), e, e.__traceback__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
