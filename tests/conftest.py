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


def settle_composition(win, app, timeout: float = 60.0) -> None:
    """Composition setup recounts after a pause (debounced, in the background) and its footer says "Updating…"
    meanwhile, with Calculate disabled (Figma State=Recalculating).  Run the pending pre-flight now and wait for
    it, as a user would wait for the footer to say Ready."""
    import time
    comp = win.composition
    if comp.mode == "sweep":
        sw = comp.sweep
        sw._timer.stop()
        sw._update_summary()
        task = sw._counter
    elif comp.mode == "expression":
        e = comp.expr
        e._parse_timer.stop()
        e._count_timer.stop()
        e.parse()
        task = e._counter
    else:
        app.processEvents()
        return
    t0 = time.perf_counter()
    while task.busy and time.perf_counter() - t0 < timeout:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
