"""Start the native ResumeForge application without a web server."""
import argparse
import os
from pathlib import Path
import re
import sys


def _launch_args(argv: list[str]) -> list[str]:
    """Finder can append a macOS process-serial-number argument on app launch.

    It is an OS launcher marker, not a ResumeForge CLI option. Keep parsing
    every other argument strictly so actual command errors remain visible.
    """
    if sys.platform != "darwin":
        return list(argv)
    return [arg for arg in argv if not re.fullmatch(r"-psn_\d+_\d+", arg)]


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
        return base / "ResumeForge" / "workspace"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/ResumeForge/workspace"
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return base / "ResumeForge" / "workspace"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Open the ResumeForge desktop application.")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    args = parser.parse_args(_launch_args(list(sys.argv[1:] if argv is None else argv)))
    from PySide6.QtWidgets import QApplication, QMessageBox
    from . import __version__
    from .desktop_window import MainWindow
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("ResumeForge")
    app.setOrganizationName("ResumeForge")
    app.setApplicationVersion(__version__)
    try:
        args.data_dir.mkdir(parents=True, exist_ok=True)
        window = MainWindow(args.data_dir)
    except Exception as exc:
        QMessageBox.critical(None, "ResumeForge startup", f"ResumeForge could not open your workspace.\n\n{exc}")
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
