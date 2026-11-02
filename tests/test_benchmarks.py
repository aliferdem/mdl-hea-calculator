"""The benchmarks in tools/ still run against the current code: each one with its --quick workloads (a few seconds),
and the large-workload guard.  Real measurements are run by hand (CONTRIBUTING.md, Benchmarks)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hea_calc import __version__

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def run(script: str, *args: str, timeout: float = 300) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    return subprocess.run([sys.executable, str(TOOLS / script), *args], capture_output=True, text=True,
                          encoding="utf-8", cwd=str(ROOT), timeout=timeout, env=env)


@pytest.mark.parametrize("script, parts", [
    ("bench_batch.py", {"generation", "engine", "pipeline", "workers", "storage"}),
    ("bench_analysis.py", None),
    ("bench_expression.py", {"parse", "generate", "pipeline"}),
])
def test_benchmark_quick_run(tmp_path, script, parts):
    out = tmp_path / "result.json"
    r = run(script, "--quick", "--out", str(out))
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["environment"]["app_version"] == __version__ and data["results"]
    if parts is not None:
        assert {rec["part"] for rec in data["results"]} == parts
    if script == "bench_analysis.py":
        assert all(q["identical"] for rec in data["results"] for q in rec["quantiles"])
    if script == "bench_expression.py":
        pipe = [rec for rec in data["results"] if rec["part"] == "pipeline"]
        dup = next(rec for rec in pipe if rec.get("document") == "duplicates")
        assert dup["duplicates"] > 0 and dup["expression"]["rows"] == dup["valid"]


def test_large_workloads_need_explicit_opt_in():
    r = run("bench_analysis.py", "--sizes", "2m", timeout=120)
    assert r.returncode != 0 and "--allow-large" in (r.stdout + r.stderr)
    r = run("bench_expression.py", "--parts", "parse", "--documents", "c3v01", timeout=120)
    assert r.returncode != 0 and "--allow-large" in (r.stdout + r.stderr)
