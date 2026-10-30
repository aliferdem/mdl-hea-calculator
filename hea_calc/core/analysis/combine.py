"""Combined collections (no Qt) - Analysis Collection "Combine runs" (2026-10-28).

A combined collection is a **logical view** over two or more calculation runs the user selected: its population is
``results WHERE run_id IN (...)`` (``CollectionScope.runs``).  Nothing is copied, merged or rewritten - the stored
runs keep every result, id and metadata, and leaving the combined scope returns to them unchanged.

Rules (documented in Help and the implementation report):

* **Compatibility.**  Runs can be combined only when their results are comparable: the same calculation engine
  version, the same dataset identifiers and the same calculation settings.  Different modes (single composition,
  composition space, expression, import) combine freely - every result carries its own composition.  A run
  without recorded provenance (older sessions) is compatible only with runs whose recorded values match it.
* **Duplicates.**  Results are never merged: the same composition calculated in two runs is two results, and each
  counts once in counts, statistics and distributions.  :func:`duplicate_compositions` reports how many
  compositions occur in more than one run, so the collection can say so.
* **Denominators.**  Statistics and model distributions use the combined population (every alive result of the
  selected runs passing the population's filter and restrictions); missing values are excluded and counted, as
  for one run.  Model N/A follows each result's own model availability.
* **Provenance.**  Every result keeps its own ``result_id`` and ``run_id``; the combined run summary
  (:func:`combined_info`) lists the source runs, and reports name them.
* **Run-specific variables.**  Design coordinates (expression variables, composition-space grid values, blocks) are
  per run: a combined collection offers the result columns (descriptors, models, composition size and family) and
  no design axis or block restriction.
"""

from __future__ import annotations

from dataclasses import replace

from .scope import COMBINED_RUN_ID

COMBINED_MODE = "combined"


def _settings(info) -> dict:
    return dict(info.settings or {})


def combine_problem(infos) -> str | None:
    """Why these runs cannot be combined, or ``None`` when they can."""
    infos = [i for i in infos if i is not None]
    if len({i.run_id for i in infos}) < 2:
        return "Select at least two calculation runs."
    first = infos[0]
    for other in infos[1:]:
        if (other.engine_version or None) != (first.engine_version or None):
            return (f"Run {other.run_id} was calculated with a different engine version "
                    f"({other.engine_version or 'not recorded'} vs {first.engine_version or 'not recorded'}).")
        if dict(other.dataset_ids or {}) != dict(first.dataset_ids or {}):
            return f"Run {other.run_id} used different datasets than Run {first.run_id}."
        if _settings(other) != _settings(first):
            return f"Run {other.run_id} used different calculation settings than Run {first.run_id}."
    return None


def compatible_with(info, selected) -> str | None:
    """Why ``info`` cannot join the ``selected`` runs (``None`` if it can, or nothing is selected yet)."""
    selected = [s for s in selected if s is not None and s.run_id != info.run_id]
    if not selected:
        return None
    return combine_problem([selected[0], info])


def combined_info(infos):
    """A run summary for the combined view (virtual run id :data:`COMBINED_RUN_ID`): the source runs, their
    elements, summed counts and their common provenance.  Never stored."""
    infos = sorted((i for i in infos if i is not None), key=lambda i: i.run_id)
    first = infos[0]
    elements: list[str] = []
    for i in infos:
        for el in i.elements or ():
            if el not in elements:
                elements.append(el)
    statuses = {i.status for i in infos}
    status = "running" if "running" in statuses else ("complete" if statuses <= {"complete"} else
                                                      next(iter(statuses - {"complete"})))
    expected = sum((i.expected or i.calculated) for i in infos)
    return replace(first, run_id=COMBINED_RUN_ID, mode=COMBINED_MODE, label="Combined runs",
                   status=status, expected=expected, calculated=sum(i.calculated for i in infos),
                   errors=sum(i.errors for i in infos), first_id=min((i.first_id for i in infos
                                                                       if i.first_id is not None), default=None),
                   last_id=max((i.last_id for i in infos if i.last_id is not None), default=None),
                   axes=[], elements=elements,
                   source={"combined": [i.run_id for i in infos],
                           "modes": {str(i.run_id): i.mode for i in infos}})


def combined_label(runs) -> str:
    return "Combined: Runs " + ", ".join(str(r) for r in sorted(runs))


def duplicate_compositions(con, runs, workspace_lo: int = 0) -> int:
    """Compositions that occur in more than one of ``runs`` (each occurrence stays its own result)."""
    runs = [int(r) for r in runs]
    if len(runs) < 2:
        return 0
    marks = ",".join("?" * len(runs))
    row = con.execute(f"SELECT COUNT(*) FROM (SELECT comp FROM results WHERE run_id IN ({marks}) AND result_id >= ? "
                      "AND comp IS NOT NULL GROUP BY comp HAVING COUNT(DISTINCT run_id) > 1)",
                      [*runs, int(workspace_lo)]).fetchone()
    return int(row[0]) if row else 0


__all__ = ["COMBINED_MODE", "combine_problem", "compatible_with", "combined_info", "combined_label",
           "duplicate_compositions"]
