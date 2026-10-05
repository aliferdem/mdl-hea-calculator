"""The real launchers start the application and exit cleanly."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("script", ["main.py", "HEA Calculator.py"])
def test_launcher_starts_and_exits(script):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HEA_CALC_AUTOQUIT_MS="300")
    proc = subprocess.run([sys.executable, str(ROOT / script)], cwd=str(ROOT), env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr
