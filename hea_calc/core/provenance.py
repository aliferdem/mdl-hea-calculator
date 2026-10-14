"""Calculation provenance: which application, engine and datasets produced a run (no Qt).

Stored with every calculation run (``runs.app_version``, ``runs.engine_version``,
``runs.dataset_ids``) so Analysis, exports and reports can state exactly what produced a result, and
so runs calculated by different engine or dataset versions are never silently treated as comparable
(data contract R1).

* **app version** - ``hea_calc.__version__``;
* **engine version** - the first 12 hex digits of the SHA-256 of the engine source
  (``core/engine.py`` and ``core/data.py``); a frozen build without sources falls back to the app
  version, marked as such;
* **dataset ids** - per data file: the first 12 hex digits of the SHA-256 of the file bytes plus the
  ``_metadata`` version/date string when the file declares one.

Everything is computed once per process (a few milliseconds) and cached.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from .. import __version__ as APP_VERSION
from .data import DATA_DIR

DATA_FILES = ("periodic_table.json", "mixing_enthalpy_data.json", "binary_formation_enthalpy_data.json")
_ENGINE_SOURCES = ("engine.py", "data.py")

# Plain-language names of the scientific datasets (reports, Toggletips).
DATASET_LABELS = {
    "periodic_table.json": "Elemental properties (Guo & Liu 2011 radii, Kittel CN12 radii, Bakker 1998 Miedema "
                           "parameters, melting points, valence electrons)",
    "mixing_enthalpy_data.json": "Takeuchi & Inoue (2005) liquid mixing enthalpies",
    "binary_formation_enthalpy_data.json": "Troparevsky et al. (2015) binary formation enthalpies",
}


def _short_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


@lru_cache(maxsize=1)
def engine_version() -> str:
    here = Path(__file__).resolve().parent
    h = hashlib.sha256()
    found = False
    for name in _ENGINE_SOURCES:
        path = here / name
        if path.is_file():
            # line endings normalised: a checkout with CRLF must not look like another engine
            h.update(path.read_bytes().replace(b"\r\n", b"\n"))
            found = True
    return h.hexdigest()[:12] if found else f"app-{APP_VERSION}"


def _metadata_version(meta: dict) -> str:
    for key in ("version", "dataset_version", "date", "updated", "last_updated", "created"):
        v = meta.get(key)
        if v:
            return str(v)
    return ""


@lru_cache(maxsize=1)
def dataset_ids() -> dict[str, str]:
    """``{file name: "sha12[ version]"}`` for the scientific data files."""
    out: dict[str, str] = {}
    for name in DATA_FILES:
        path = DATA_DIR / name
        try:
            raw = path.read_bytes()
        except OSError:
            out[name] = "missing"
            continue
        ident = _short_sha(raw.replace(b"\r\n", b"\n"))
        try:
            meta = json.loads(raw.decode("utf-8")).get("_metadata", {})
        except (ValueError, UnicodeDecodeError, AttributeError):
            meta = {}
        version = _metadata_version(meta) if isinstance(meta, dict) else ""
        out[name] = f"{ident} {version}".strip()
    return out


def run_provenance() -> dict:
    """The provenance fields stored with a new calculation run."""
    return {"app_version": APP_VERSION, "engine_version": engine_version(), "dataset_ids": dataset_ids()}
