"""Build tool: compile the app with Nuitka into a portable folder and archive it.

Run from the project root (Nuitka needs a C compiler: MSVC on Windows, gcc on Linux):

    uv run --group build tools/build.py

Writes ``dist/HEA-Calculator-<version>-windows-portable.zip`` on Windows (the app's files at the top) and
``dist/HEA-Calculator-<version>-linux-portable.tar.gz`` on Linux (one ``HEA Calculator`` folder).  Either runs
without Python.  Nuitka's working files go to ``build/``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
DIST = ROOT / "dist"
NAME = "HEA Calculator"
sys.path.insert(0, str(ROOT))

from hea_calc import __version__


def main() -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if version != __version__:
        sys.exit(f"pyproject.toml version {version} != hea_calc.__version__ {__version__}")
    windows = sys.platform == "win32"

    args = [
        "--mode=standalone",
        "--enable-plugin=pyside6",
        "--include-package-data=hea_calc",                 # docs, fonts, icons, equations, illustrations
        "--include-data-dir=data=data",                    # found next to the package (core/data.py)
        "--include-data-files=LICENSE.txt=LICENSE.txt",
        "--include-data-dir=license=license",
        # openpyxl imports these when they are installed (the dev group has them); the app does not use them
        "--nofollow-import-to=numpy",
        "--nofollow-import-to=PIL",
        # the About window reads their versions with importlib.metadata
        "--include-distribution-metadata=openpyxl",
        "--include-distribution-metadata=XlsxWriter",
        "--company-name=MDL",
        f"--product-name={NAME}",
        f"--file-version={version}",
        f"--product-version={version}",
        f"--output-filename={NAME}",
        f"--output-folder-name={NAME}",
        f"--output-dir={BUILD}",
        "--assume-yes-for-downloads",
    ]
    if windows:
        args += ["--windows-console-mode=disable", "--windows-icon-from-ico=hea_calc/ui/icons/logo_icon.ico"]
    subprocess.run([sys.executable, "-m", "nuitka", *args, "main.py"], cwd=ROOT, check=True)

    portable = BUILD / "portable"
    shutil.rmtree(portable, ignore_errors=True)
    portable.mkdir()
    (BUILD / f"{NAME}.dist").rename(portable / NAME)
    shutil.rmtree(DIST, ignore_errors=True)
    DIST.mkdir()
    stem = f"HEA-Calculator-{version}-{'windows' if windows else 'linux'}-portable"
    if windows:
        # the files at the top: Explorer's Extract All already makes a folder named after the zip
        archive = shutil.make_archive(str(DIST / stem), "zip", portable / NAME)
    else:
        # one "HEA Calculator/" folder, as tar archives usually unpack (tar makes no folder of its own)
        archive = shutil.make_archive(str(DIST / stem), "gztar", portable, NAME)
    print(f"{Path(archive).relative_to(ROOT)}  {Path(archive).stat().st_size / 2**20:.0f} MB")


if __name__ == "__main__":
    main()
