"""Collection scope: the explicitly resolved population of Collection analysis (data contract section 5).

A scope names **one** calculation run (rule R1: runs are never mixed silently; composite collections are
not part of v1), one base population and optional conjunctive restrictions:

    population = alive ∩ run ∩ base ∩ families ∩ sizes ∩ blocks

* ``full``     - every alive result of the run;
* ``filtered`` - the run's results passing a *copy* of the Results-table filter taken when the scope
  was resolved (same SQL semantics as the table, ``repository.filter_sql``);
* ``checked``  - a *snapshot* of the checked results (``vw.<snapshot>`` id table) taken when the scope
  was resolved.

Stored results never change after they are written - removal deletes them - so a scope is a predicate
(plus, for checked results, a snapshot table): removed results leave every population at once and
nothing else can change it.  Table interactions (sort, page, hover, double-click, filter edits,
checking rows) never re-resolve a scope; the state holder only flags it *stale*.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, replace

from ..repository import filter_sql, q
from ..results import IdSetFilter, ModelFilter, RangeFilter

FULL, FILTERED, CHECKED = "full", "filtered", "checked"
BASES = (FULL, FILTERED, CHECKED)
BASE_LABELS = {FULL: "Full result set", FILTERED: "Filtered result set", CHECKED: "Checked results"}


def freeze_filters(filters) -> tuple:
    """Hashable, order-independent copy of Results-table filters."""
    out = []
    for f in filters or ():
        if isinstance(f, RangeFilter):
            out.append(("range", f.key, f.minimum, f.maximum))
        elif isinstance(f, ModelFilter):
            out.append(("model", f.key, tuple(sorted(f.labels))))
        elif isinstance(f, IdSetFilter):
            out.append(("ids", f.table, len(f.ids)))
        elif isinstance(f, tuple):
            out.append(f)
        else:
            raise ValueError(f"Unsupported filter {f!r}")
    return tuple(sorted(out, key=repr))


def thaw_filters(frozen: tuple) -> list:
    out = []
    for f in frozen:
        if f[0] == "range":
            out.append(RangeFilter(f[1], f[2], f[3]))
        elif f[0] == "model":
            out.append(ModelFilter(f[1], set(f[2])))
        elif f[0] == "ids":
            out.append(IdSetFilter(f[1]))
    return out


def filter_text(frozen: tuple) -> str:
    """Plain description of a frozen filter ("M8 = SS; δ ≥ 6")."""
    from .metrics import DESCRIPTORS, format_value
    parts = []
    for f in frozen:
        if f[0] == "model":
            parts.append(f"{f[1]} = {' or '.join(f[2])}")
        elif f[0] == "ids":
            parts.append(f"{f[2]:,} results selected in Analysis")
        else:
            d = DESCRIPTORS.get(f[1])
            name = d.plain if d else f[1]
            lo, hi = f[2], f[3]
            if lo is not None and hi is not None:
                parts.append(f"{format_value(f[1], lo)} ≤ {name} ≤ {format_value(f[1], hi)}")
            elif lo is not None:
                parts.append(f"{name} ≥ {format_value(f[1], lo)}")
            elif hi is not None:
                parts.append(f"{name} ≤ {format_value(f[1], hi)}")
    return "; ".join(parts)


@dataclass(frozen=True)
class CollectionScope:
    """Definition of a collection.  Equality and the key ignore ``scope_id`` (equal definitions are equal)."""
    run_id: int
    base: str = FULL
    filters: tuple = ()                      # frozen filter copy (base = filtered)
    snapshot: str | None = None              # vw table of checked ids (base = checked)
    snapshot_count: int = 0                  # checked results when the snapshot was taken
    families: tuple[str, ...] | None = None
    sizes: tuple[int, ...] | None = None
    blocks: tuple[int, ...] | None = None
    scope_id: str = field(default_factory=lambda: uuid.uuid4().hex, compare=False)

    def __post_init__(self):
        if self.base not in BASES:
            raise ValueError(f"Unknown population {self.base!r}")
        if self.base == CHECKED and not self.snapshot:
            raise ValueError("A checked-results scope needs a snapshot table")

    # -------------------------------------------------------------- identity
    def definition(self) -> dict:
        return {"run": self.run_id, "base": self.base, "filters": [list(f) for f in self.filters],
                "snapshot": self.snapshot if self.base == CHECKED else None,
                "families": sorted(self.families) if self.families else None,
                "sizes": sorted(self.sizes) if self.sizes else None,
                "blocks": sorted(self.blocks) if self.blocks else None}

    def key(self) -> str:
        return hashlib.sha1(json.dumps(self.definition(), sort_keys=True, default=str).encode()).hexdigest()[:16]

    @property
    def restricted(self) -> int:
        """Number of active restrictions ("Restrict (2)")."""
        return sum(1 for r in (self.families, self.sizes, self.blocks) if r)

    def with_restrictions(self, families=None, sizes=None, blocks=None) -> "CollectionScope":
        return replace(self, families=tuple(families) or None if families else None,
                       sizes=tuple(sizes) or None if sizes else None,
                       blocks=tuple(blocks) or None if blocks else None, scope_id=uuid.uuid4().hex)

    def without_restrictions(self) -> "CollectionScope":
        return replace(self, families=None, sizes=None, blocks=None, scope_id=uuid.uuid4().hex)

    # -------------------------------------------------------------- SQL
    def sql(self, workspace_lo: int = 0, alias: str = "r") -> tuple[str, str, list]:
        """``(from, where, params)``: ``SELECT ... FROM {from} WHERE {where}`` is the population.

        ``workspace_lo`` is the first id of the Results table's workspace: rows below it were cleared
        from the table (and are being deleted), so they are never part of a collection."""
        r = alias
        frm = f"results {r}"
        if self.base == CHECKED:
            frm += f" JOIN vw.{q(self.snapshot)} s_ ON s_.rid = {r}.result_id"
        where = [f"{r}.run_id = ?", f"{r}.result_id >= ?"]
        params: list = [int(self.run_id), int(workspace_lo)]
        if self.base == FILTERED and self.filters:
            fw, fp = filter_sql(thaw_filters(self.filters))
            # filter_sql emits unqualified results columns; qualify them for joins
            where.append("1" + fw)
            params += list(fp)
        if self.families:
            where.append(f"{r}.family_id IN (SELECT family_id FROM families WHERE key IN "
                         f"({','.join('?' * len(self.families))}))")
            params += list(self.families)
        if self.sizes:
            where.append(f"{r}.n_elements IN ({','.join('?' * len(self.sizes))})")
            params += [int(s) for s in self.sizes]
        if self.blocks:
            where.append(f"{r}.block IN ({','.join('?' * len(self.blocks))})")
            params += [int(b) for b in self.blocks]
        return frm, " AND ".join(where), params

    # -------------------------------------------------------------- text
    def population_text(self) -> str:
        return BASE_LABELS[self.base]

    def restriction_text(self) -> str:
        parts = []
        if self.families:
            parts.append("Family: " + ", ".join(self.families))
        if self.sizes:
            parts.append(", ".join(str(s) for s in sorted(self.sizes)) + " elements")
        if self.blocks:
            parts.append("Block " + ", ".join(str(b + 1) for b in sorted(self.blocks)))
        return " · ".join(parts)


@dataclass(frozen=True)
class ResolvedScope:
    """A scope with the population size it had when resolved (``n``) and the state it was resolved
    from (filter copy / checked-set version) - the basis of the stale notices."""
    scope: CollectionScope
    n: int
    resolved_at: str
    filter_snapshot: tuple = ()
    checked_version: int = 0
    data_version: int = 0
