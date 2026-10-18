"""Locate web assets in a source checkout or installed package."""

from pathlib import Path


def asset_directory(name):
    package = Path(__file__).resolve().parent
    bundled = package / "_assets" / name
    return bundled if bundled.is_dir() else package.parent / name
