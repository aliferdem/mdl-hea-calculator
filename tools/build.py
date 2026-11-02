"""Build tool: compile the app with Nuitka into a portable folder and archive it.

Run from the project root (Nuitka needs a C compiler: MSVC on Windows, gcc on Linux):

    uv run --group build tools/build.py

Writes ``dist/HEA-Calculator-<version>-windows-portable.zip`` on Windows (the app's files at the top) and
``dist/HEA-Calculator-<version>-linux-portable.tar.gz`` on Linux (one ``HEA Calculator`` folder).  Either runs
without Python.  Nuitka's working files go to ``build/``.  ``LICENSE.txt`` and ``THIRD-PARTY-NOTICES.txt`` go next to
the program; the build stops first if the notices miss a bundled package or list another version of it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
DIST = ROOT / "dist"
NAME = "HEA Calculator"
NOTICES = "THIRD-PARTY-NOTICES.txt"
sys.path.insert(0, str(ROOT))

from hea_calc import __version__


def main() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    if version != __version__:
        sys.exit(f"pyproject.toml version {version} != hea_calc.__version__ {__version__}")
    check_notices(project["dependencies"])
    windows = sys.platform == "win32"

    args = [
        "--mode=standalone",
        "--enable-plugin=pyside6",
        "--include-package-data=hea_calc",                 # docs, fonts, icons, equations, illustrations
        "--include-data-dir=data=data",                    # found next to the package (core/data.py)
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
    for name in ("LICENSE.txt", NOTICES):
        shutil.copy2(ROOT / name, portable / NAME / name)
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


def check_notices(dependencies: list[str]) -> None:
    """Stop unless THIRD-PARTY-NOTICES.txt has an entry for Python and each bundled package, at its version."""
    notices = (ROOT / NOTICES).read_text(encoding="utf-8")
    # Nuitka's runtime library is compiled into the program
    dists = [*bundled_distributions(dependencies), metadata.distribution("nuitka")]
    expected = [f"Python {sys.version_info[0]}.{sys.version_info[1]}"]
    expected += [f"{dist.metadata['Name']} {dist.version}" for dist in dists]
    if missing := [entry for entry in expected if entry not in notices]:
        sys.exit(f"{NOTICES} lacks {', '.join(missing)}: add or update their entries (licence texts are in each "
                 "package's .dist-info folder)")


def bundled_distributions(dependencies: list[str]) -> list[metadata.Distribution]:
    """The installed packages the app depends on, directly or not: Nuitka compiles them into the program."""
    found: dict[str, metadata.Distribution] = {}
    todo = list(dependencies)
    while todo:
        requirement = todo.pop()
        if "extra ==" in requirement:                                     # optional features the app does not ask for
            continue
        name = re.match(r"[A-Za-z0-9._-]+", requirement)[0]
        if normalize(name) in found:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:                             # left out on this platform by a marker
            continue
        found[normalize(name)] = dist
        todo += dist.requires or []
    return list(found.values())


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


if __name__ == "__main__":
    main()
