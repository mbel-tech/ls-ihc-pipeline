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
SELFTEST_LOG = os.path.join(REPO, "lsapp-selftest.log")


def _report(exc_type, exc, tb):
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        with open(CRASH_LOG, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        pass
    try:
        if sys.stderr is not None:
            sys.stderr.write(text)
    except Exception:                                       # noqa: BLE001
        pass
    # Not under --self-test: a modal dialog with nobody to dismiss it turns a
    # crash into a hang, which is strictly worse than the silent exit this
    # reporter exists to replace.
    if "--self-test" in sys.argv:
        return
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
        # A bare traceback here is the least useful thing this can print: the
        # cause is almost always the interpreter rather than a broken install,
        # and the traceback says nothing about which one is running. Name it,
        # and name the fix. run_app.bat now prefers work\\appenv for the same
        # reason; this is what someone running `python -m app` by hand sees.
        sys.stderr.write(
            f"\nPySide6 is not installed in this interpreter.\n"
            f"  running: {sys.executable}\n"
            f"  version: {sys.version.split()[0]}\n\n"
            f"work\\appenv is the interpreter that has it - the same 3.13 venv "
            f"build_app.bat freezes the exe from. (It is 3.13 rather than 3.14 "
            f"because pylibCZIrw, which the overview stage needs, publishes no "
            f"cp314 wheel.)\n\n"
            f"Use it:\n"
            f"  run_app.bat\n"
            f"or build it:\n"
            f"  build_app.bat\n"
            f"or install into this one:\n"
            f"  pip install -r requirements.txt\n\n")
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

        if "--self-test" in sys.argv:
            return _self_test(app, w)

        return app.exec()
    except BaseException as e:                              # noqa: BLE001
        _report(type(e), e, e.__traceback__)
        return 1


def _self_test(app, w):
    """Load a curator, report whether it rendered, exit.

    A frozen build cannot be clicked through from a script, and the window
    appearing proves nothing about QtWebEngine - the helper process, its
    resources and the local server are all still untested at that point. This is
    how a build is checked on a machine nobody is sitting at, including a
    colleague's after they download it.
    """
    from PySide6.QtCore import QTimer
    import stages as S

    results = {}
    target = next((st for st in S.STAGES if st.curator), None)

    def finish():
        # A windowed build has sys.stdout = None, so print() raises here - and
        # because finish() is what calls app.exit(), that exception hung the
        # whole run, watchdog included. The results go to a file as well as the
        # console, and nothing in reporting is allowed to stop the exit.
        lines = [f"  {'PASS' if ok else 'FAIL'}  {name}"
                 for name, ok in results.items()]
        code = 0 if results and all(results.values()) else 1
        lines.append(f"  self-test {'PASSED' if code == 0 else 'FAILED'}")
        try:
            with open(SELFTEST_LOG, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except OSError:
            pass
        try:
            if sys.stdout is not None:
                sys.stdout.write("\n".join(lines) + "\n")
                sys.stdout.flush()
        except Exception:                                   # noqa: BLE001
            pass
        app.exit(code)

    results["window"] = w.isVisible()
    results["local server"] = bool(w.server.port)
    results["stages listed"] = w.list.count() > 5

    if target is None:
        results["curator"] = False
        QTimer.singleShot(0, finish)
        return app.exec()

    def loaded(ok):
        results["curator renders (" + target.curator + ")"] = bool(ok)
        QTimer.singleShot(300, finish)

    w.curator.view.loadFinished.connect(loaded)
    w.curator.show_page(target.curator, target.title)
    QTimer.singleShot(45000, finish)          # never hang a CI-style run
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
