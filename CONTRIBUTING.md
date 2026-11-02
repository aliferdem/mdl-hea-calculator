# Contributing to HEA Calculator

This document collects the architecture and development notes for HEA Calculator. Installation and use are
described in [`README.md`](README.md); the scientific implementation is documented in
[`CALCULATION_AUDIT.md`](docs/CALCULATION_AUDIT.md).

## Architecture

The main parts of the project are organized as follows:

```text
main.py                 entry point (spawn-safe for worker processes)
hea_calc/
  core/                 Qt-free logic
    engine.py           calculation engine: descriptors, M1–M8 and data-availability rules
    data.py             dataset loading (data/*.json, with provenance metadata)
    references.py       numbered bibliography shown in About, Help, Analysis and PDF reports
    composition.py      unit conversion (at. ratio, at.%, wt.%, mass)
    generation.py       composition-space enumeration and exact counting
    expression*.py      expression lexer, parser, diagnostics and compiled evaluator
    jobs.py, recipes.py worker-process pool and batch generation
    repository.py       session SQLite result store; SQL sorting, filtering and export
    analysis/           collection queries, statistics and report content
  ui/                   PySide6 widgets, theme tokens, icons, Analysis views and Windows title-bar integration
  docs/pages/           in-app documentation (Markdown)
data/                   elemental properties, Takeuchi & Inoue ΔH_mix and Troparevsky ΔH_f
tests/                  pytest tests; tests/reference/ contains values transcribed from publications,
                        _support.py shared test helpers, _native_*.py scripts run by the native Windows tests
tools/                  performance benchmarks and generators of committed data and assets (see below)
```

The calculation engine is separated from the Qt interface. The interface displays the descriptors and
classifications returned by the engine rather than calculating them independently. For batch operations, the workers
send portions of the results to one writer process. The results table, analysis functions and export operations then
retrieve the required data from SQLite. Therefore, the complete batch does not have to be stored in the memory of a
single process.

## Development

The tests can be executed from the project directory using the following commands:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
uv run pytest -q
```

The complete test suite contains approximately 1,650 tests and takes about 3–4 minutes on a 16-core Linux
machine. Tests involving native windows are optional and require a Windows desktop session. They can be enabled by
setting `HEA_NATIVE_TESTS=1`.

The code is checked with [ruff](https://docs.astral.sh/ruff/) (settings in `pyproject.toml`) on every pull request
and every push to `main`. The same check can be run locally before committing; `--fix` removes unused imports and
similar leftovers automatically:

```powershell
uv run ruff check --fix
```

When changing an equation, constant, numerical boundary or dataset value, the corresponding publication should be
checked. The change must also be documented in `CALCULATION_AUDIT.md`, which describes the current implementation,
and supported by a regression test against published numerical results. The reasoning and evidence behind a change
are added as a dated entry to `docs/SCIENTIFIC_DEVELOPMENT_HISTORY.md`.

The equations in `README.md` and `CALCULATION_AUDIT.md` are written in GitHub's LaTeX syntax. GitHub applies Markdown
before rendering the mathematics, so inside `$…$` and `$$…$$` avoid `<`, `>` and `|` (use `\lt`, `\gt`, `\lvert`
and `\rvert`), backslash escapes such as `\,` or `\%`, `*`, and `_` directly after a non-alphanumeric character
(write `c_A^{\mathrm{s}}` rather than `c^{\mathrm{s}}_A`). The in-app Help pages do not render LaTeX and keep their
own notation.

## Developer tools

The scripts in `tools/` are not part of the application. Each describes its usage in its docstring.

### Benchmarks

The benchmarks run the application's own code without the window: the worker pool, the single writer process, the
SQLite repository and the Analysis queries. Each prints one JSON line per measurement, with the application version
and engine fingerprint, and writes all results to a file with `--out`. `--quick` runs tiny workloads (a few seconds;
the test suite runs every benchmark this way), and workloads above 1,000,000 compositions or rows are refused unless
`--allow-large` is given.

| Script | Measures |
|---|---|
| `bench_batch.py` | Composition generation and exact counting, calculation throughput of the engine (descriptors and M1–M8), the complete Calculate path for increasing batch sizes, worker-process scaling, SQLite insertion rate and bytes per row, and peak memory of the main, writer and worker processes |
| `bench_analysis.py` | Collection queries on synthetic result sets: row count and population, statistics with exact and binned quartiles, statistics by family, the two exact quartile methods (which must agree), class distributions, histogram, binned and sampled scatter data |
| `bench_expression.py` | Expression parsing and validation, the pre-flight count with duplicate detection, generation throughput, multiple blocks, duplicate removal, a constrained three-variable sweep, and the Calculate path for expressions and equivalent composition spaces (`--verify` compares them value by value) |

```powershell
uv run tools/bench_batch.py
uv run tools/bench_batch.py --parts pipeline,workers --sizes 100k,1m --scaling-size 200k --out bench.json
uv run tools/bench_analysis.py --sizes 100k,1m
uv run tools/bench_expression.py --verify
uv run tools/bench_analysis.py --sizes 5m --allow-large
```

The synthetic result sets of the storage and Analysis measurements repeat the engine results of 50 alloys
(`tests/_support.py`). They measure storage and queries only; timings depend on the machine, so results are compared
on the same computer and application version.

### Generators

These scripts regenerate files that are committed to the repository.

| Script | Generates |
|---|---|
| `build_model_figures.py` | `data/model_figures.json`, the published values plotted in *Model details*, from `tests/reference/published_benchmarks.json` |
| `render_equations.py` | the equation images in `hea_calc/ui/equations/` (requires matplotlib, installed with the dev group) |
| `help_screenshots.py` | the screenshots of the in-app documentation in `hea_calc/docs/images/` |

## Dependencies

pytest and matplotlib are development tools, which are not required at runtime; `uv sync` installs them by default.
Nuitka, used for the optional Windows build, is installed with `uv sync --group build`. After a dependency change in
`pyproject.toml`, `uv lock` updates `uv.lock`, and `requirements.txt` is regenerated with the command recorded at the
top of that file. A new dependency or bundled asset (font, icon) must also be listed in the
License section of the README, and a bundled asset keeps its licence file beside it.

## References

The bibliography is defined once, in `hea_calc/core/references.py`. The About window, *Help › Scientific References*,
the model details in Analysis and the PDF reports are generated from it. The README cites the same entries as GitHub
footnotes `[^1]`–`[^14]`, whose definitions are at the end of `README.md`. GitHub numbers footnotes in the order of
their first citation, so the README cites [^1]–[^8] in its introduction and [^9]–[^14] in *Descriptors and models*,
which keeps the displayed numbers equal to those of the application. When an entry changes, the README must be
updated to match; `tests/test_about.py` compares the two.

## Versioning

Version numbers follow [Semantic Versioning](https://semver.org/) and are written in the
[PEP 440](https://peps.python.org/pep-0440/) form used by Python packaging:

| Stage | Example | Meaning |
|---|---|---|
| Development release | `1.1.0.dev1` | Work in progress towards the next version; not distributed. |
| Release candidate | `1.0.0rc1` | Feature-complete candidate for the stable release; only corrections are made before it. |
| Stable release | `1.0.0` | A published release (Git tag `v1.0.0`). |
| Patch release | `1.0.1` | Corrections that change neither the features nor the meaning of results. |

A minor version (`1.1.0`) adds functionality. A major version (`2.0.0`) is used when results or stored data are no
longer comparable with the previous version, for example after a change to a model criterion or dataset.

The version is defined in `hea_calc/__init__.py` (`__version__`), which the About window, PDF reports and the run
metadata of the results database read. `pyproject.toml` repeats it because the project has no build backend that could
read it from the package. `uv.lock` records it as well and is updated with `uv lock`. The version also appears once in
the Installation section of the README and in `CITATION.cff`. `tests/test_about.py` checks that all of these agree.

To change the version, edit `hea_calc/__init__.py`, `pyproject.toml`, `CITATION.cff` and the README, then run
`uv lock`. A Windows build must use the same version; Windows file-version fields accept only numbers, so
`1.0.0rc1` is written there as `1.0.0.0`.
