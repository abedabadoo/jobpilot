"""Open generated documents in the user's configured desktop application."""

import os
import subprocess
import sys
from pathlib import Path


def open_document(target: Path) -> None:
    if os.name == "nt":
        os.startfile(str(target))
    else:
        command = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen(
            [command, str(target)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
