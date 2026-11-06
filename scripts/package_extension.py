"""Package the unpacked Chrome extension without profiles, tokens or test grants."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path

RUNTIME_FILES = (
    "manifest.json",
    "background.js",
    "core.js",
    "content.js",
    "popup.html",
    "popup.js",
    "options.html",
    "options.js",
    "style.css",
    "README.md",
)


def package(source: Path, output: Path) -> Path:
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    if not re.fullmatch(r"\d+(?:\.\d+){0,3}", version):
        raise ValueError("Invalid extension version")
    for name in RUNTIME_FILES:
        path = source / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing or linked runtime file: {name}")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"JobPilot-Autofill-{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in RUNTIME_FILES:
            bundle.write(source / name, f"JobPilot-Autofill/{name}")
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/extension"))
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / "extension"
    print(package(source, args.output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
