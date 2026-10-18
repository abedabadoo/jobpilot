"""Restore local services when optional Windows startup is enabled."""

import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
import launcher  # noqa: E402 -- the installed launcher is above this script


def main():
    paths = launcher.app_paths()
    data = Path(os.environ.get("JOBPILOT_DATA_DIR", paths["data"])).resolve()
    database = data / "jobpilot.sqlite"
    if not database.is_file():
        return
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT value FROM settings WHERE key=?", ("settings",)).fetchone()
    if not row or not json.loads(row[0]).get("startup", False):
        return
    (data / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=data / "logs" / "recovery.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        launcher.ensure_services(paths, data)
    except Exception:
        logging.exception("JobPilot service recovery failed")
        raise


if __name__ == "__main__":
    main()
