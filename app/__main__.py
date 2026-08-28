"""Entry point: python -m app  (from the repo root), or run_app.bat.

Config is found beside the repo, not beside this file, so a frozen build that
ships `app/` inside the bundle still reads the user's real config.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def main():
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication(sys.argv)
    app.setApplicationName("LS IHC pipeline")

    cfg = os.path.join(REPO, "config.json")
    if not os.path.exists(cfg):
        QMessageBox.critical(
            None, "No config.json",
            f"Expected {cfg}.\n\nCopy config.example.json to config.json and "
            "fill in source_dir, out_root and atlas_pdf.")
        return 1

    from main_window import MainWindow
    w = MainWindow(REPO)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
