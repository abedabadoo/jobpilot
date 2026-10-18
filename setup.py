"""Include the dashboard and portal in wheel installations."""

from pathlib import Path
from shutil import copytree

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithAssets(build_py):
    def run(self):
        super().run()
        root = Path(__file__).parent
        destination = Path(self.build_lib) / "jobpilot" / "_assets"
        for name in ("web", "remote_web"):
            copytree(root / name, destination / name, dirs_exist_ok=True)


setup(cmdclass={"build_py": BuildWithAssets})
