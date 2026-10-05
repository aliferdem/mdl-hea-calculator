import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REF = Path(__file__).resolve().parent / "reference"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(REF) not in sys.path:
    sys.path.insert(0, str(REF))

from hea_calc.core.engine import Engine  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    return Engine()
