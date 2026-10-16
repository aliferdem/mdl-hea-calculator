"""Repository queries of Collection analysis (no Qt).  Run on a worker thread with its own read-only
connection (``ResultRepository.reader_connection``); SQLite executes them in C with the GIL released,
and Python only touches aggregated rows or bounded point arrays - never the whole population.

Every function takes a :class:`ScopeQuery` (a resolved scope + its run) and returns plain Python data.
Missing values (SQL NULL) are excluded and counted, never plotted or averaged as zero.  A query can be
stopped from another thread with ``ScopeQuery.cancel()`` (``sqlite3.Connection.interrupt``); it then
raises :class:`QueryCancelled`.
"""

from __future__ import annotations

import math
import sqlite3
from array import array
from dataclasses import dataclass

from ..chunks import NA_CODES, NA_NAMES, STATUS_CODES, STATUS_NAMES
from ..engine import MODEL_KEYS, NA, NA_ERROR, NA_MISSING_DATA, NA_UNDEFINED
from ..repository import RunInfo, design_table, q
from .metrics import DESCRIPTORS, METRIC_KEYS, decimals_for
from .models import CLASSES
from .scope import CollectionScope
from .stats import QUARTILES, type7_positions

RAW_POINT_LIMIT = 50_000          # plotting spec section 4: RAW up to this many points
SAMPLE_TARGET = 20_000            # points drawn in a sampled scatter
EXACT_QUANTILE_MAX = 2_000_000    # above: quartiles from a fine histogram (disclosed as approximate)
APPROX_BINS = 4096
QUANTILE_SELECT_MIN = 20_000      # below: one sort is already cheap
FETCH_CHUNK = 5_000
_HASH_MUL = 2654435761            # Knuth multiplicative hash: deterministic per result id (fixed seed)
_HASH_MOD = 4294967296


class QueryCancelled(Exception):
    pass


# ====================================================================== metrics of a run
@dataclass(frozen=True)
class PlotMetric:
    id: str
    symbol: str          # HTML
    plain: str
    name: str
    unit: str
    sql: str             # expression over r (results), d (design table)
    kind: str = "descriptor"   # descriptor | variable | fraction | grid | count
    decimals: int = 2
    log_default: bool = False
    undefined_sql: str = ""
    ordered: bool = False      # a design axis along which a path can be ordered
    source_note: str = ""

    @property
    def needs_design(self) -> bool:
        return "d." in self.sql

    def axis_title(self) -> str:
        unit = self.unit or "–"
        title = f"{self.symbol} ({unit})"
        return f"{title} — {self.source_note}" if self.source_note else title

    def plain_title(self) -> str:
        return f"{self.plain} ({self.unit or '-'})"

    def selector_text(self) -> str:
        return f"{self.symbol} — {self.name} ({self.unit or '–'})"


def descriptor_metric(key: str) -> PlotMetric:
    d = DESCRIPTORS[key]
    return PlotMetric(key, d.symbol, d.plain, d.name, d.unit, f"r.{q(key)}", "descriptor", d.decimals,
                      d.log_default, d.undefined_sql, False, d.source_note)


N_ELEMENTS = PlotMetric("n_elements", "n", "n", "Number of elements", "", "r.n_elements", "count", 0)


def run_metrics(info: RunInfo | None) -> list[PlotMetric]:
    """Design axes of the run (expression variables, element concentrations), n, then descriptors."""
    out: list[PlotMetric] = []
    if info is not None:
        el_axes = [a for a in info.axes if a.get("kind") == "element" and a.get("col")]
        for a in info.axes:
            if a.get("kind") == "variable" and a.get("col"):
                out.append(PlotMetric(f"var:{a['name']}", f"<i>{a['name']}</i>", a["name"],
                                      f"Expression variable {a['name']}", "", f"d.{q(a['col'])}", "variable", 3,
                                      ordered=True))
        for a in info.axes:
            if a.get("kind") == "fraction" and a.get("col"):
                el = a.get("element") or a["name"].split()[0]
                out.append(PlotMetric(f"at:{el}", f"x<sub>{el}</sub>", f"x_{el}", "Element concentration", "at.%",
                                      f"d.{q(a['col'])}", "fraction", 2))
        if info.mode == "sweep" and el_axes:
            ratio = info.source.get("unit") != "at"
            total = " + ".join(f"d.{q(a['col'])}" for a in el_axes)
            for a in el_axes:
                sql = f"(100.0 * d.{q(a['col'])} / ({total}))" if ratio else f"d.{q(a['col'])}"
                out.append(PlotMetric(f"at:{a['name']}", f"x<sub>{a['name']}</sub>", f"x_{a['name']}",
                                      "Element concentration", "at.%", sql, "fraction", 2))
                if ratio:
                    out.append(PlotMetric(f"grid:{a['name']}", f"Grid {a['name']}", f"grid_{a['name']}",
                                          f"Grid value of {a['name']}", "at. ratio", f"d.{q(a['col'])}", "grid", 3,
                                          ordered=True))
    out.append(N_ELEMENTS)
    out += [descriptor_metric(k) for k in METRIC_KEYS]
    return out


def metric_by_id(info: RunInfo | None, mid: str) -> PlotMetric:
    for m in run_metrics(info):
        if m.id == mid:
            return m
    raise KeyError(f"Unknown metric {mid!r} for this run")


# ====================================================================== categorical dimensions
DIM_NONE, DIM_FAMILY, DIM_SIZE, DIM_BLOCK, DIM_CSTR = "none", "family", "size", "block", "cstr"
STATUS_DIM_NAMES = {0: "In domain", 1: "Extrapolated", 2: "Flagged data"}


def dim_label(dim: str) -> str:
    if dim.startswith("model:"):
        from .models import title
        return title(dim[6:])
    if dim.startswith("status:"):
        return f"{dim[7:]} status"
    return {DIM_NONE: "None", DIM_FAMILY: "Element family", DIM_SIZE: "System size", DIM_BLOCK: "Expression block",
            DIM_CSTR: "Crystal structure (VEC rule)"}.get(dim, dim)


def dim_sql(dim: str) -> str:
    """SQL expression of a categorical dimension (``f`` = families joined on ``r.family_id``)."""
    if dim == DIM_FAMILY:
        return "f.key"
    if dim == DIM_SIZE:
        return "r.n_elements"
    if dim == DIM_BLOCK:
        return "r.block"
    if dim == DIM_CSTR:
        return "r.cstr"
    if dim.startswith("model:"):
        k = dim[6:]
        if k not in MODEL_KEYS:
            raise KeyError(dim)
        return f"COALESCE(r.{q(k)}, '{NA}')"
    if dim.startswith("status:"):
        k = dim[7:]
        if k not in MODEL_KEYS:
            raise KeyError(dim)
        return (f"CASE WHEN r.{q('status_' + k)} IS NULL THEN 'Not available' "
                + " ".join(f"WHEN r.{q('status_' + k)} = {c} THEN '{n}'" for c, n in STATUS_DIM_NAMES.items())
                + " END")
    raise KeyError(dim)


def dim_order(dim: str, values) -> list:
    """Display order of category values."""
    vals = [v for v in values]
    if dim.startswith("model:"):
        order = list(CLASSES.get(dim[6:], ())) + [NA]
        return sorted(vals, key=lambda v: order.index(v) if v in order else len(order))
    if dim.startswith("status:"):
        order = ["In domain", "Extrapolated", "Flagged data", "Not available"]
        return sorted(vals, key=lambda v: order.index(v) if v in order else 9)
    if dim in (DIM_SIZE, DIM_BLOCK):
        return sorted(vals, key=lambda v: (v is None, v if v is not None else 0))
    if dim == DIM_CSTR:
        order = ["FCC", "BCC + FCC", "BCC"]
        return sorted(vals, key=lambda v: order.index(v) if v in order else 9)
    return sorted(vals, key=lambda v: (v is None, str(v)))


def dim_value_text(dim: str, v) -> str:
    if v is None:
        return "Not evaluable" if dim in (DIM_FAMILY, DIM_SIZE) else "—"
    if dim == DIM_SIZE:
        return f"{v} elements"
    if dim == DIM_BLOCK:
        return f"Block {int(v) + 1}"
    return str(v)


# ====================================================================== the query object
class ScopeQuery:
    """Queries over one resolved scope.  Thread-confined to the connection's thread except ``cancel``."""

    def __init__(self, con: sqlite3.Connection, scope: CollectionScope, info: RunInfo | None, workspace_lo: int = 0):
        self.con = con
        self.scope = scope
        self.info = info
        self.lo = workspace_lo
        self.frm, self.where, self.params = scope.sql(workspace_lo)
        self._design = bool(info and any(a.get("col") for a in info.axes))
        self._cancelled = False

    # -------------------------------------------------------------- plumbing
    def cancel(self) -> None:
        self._cancelled = True
        try:
            self.con.interrupt()
        except Exception:                      # noqa: BLE001 - connection already closed
            pass

    def _from(self, design: bool = False, family: bool = False) -> str:
        frm = self.frm
        if design and self._design:
            frm += f" LEFT JOIN {q(design_table(self.scope.run_id))} d ON d.result_id = r.result_id"
        if family:
            frm += " LEFT JOIN families f ON f.family_id = r.family_id"
        return frm

    def _exec(self, sql: str, params=()) -> sqlite3.Cursor:
        if self._cancelled:
            raise QueryCancelled()
        try:
            return self.con.execute(sql, list(params))
        except sqlite3.OperationalError as exc:
            if "interrupt" in str(exc).lower() or self._cancelled:
                raise QueryCancelled() from exc
            raise

    def _fetchall(self, cur: sqlite3.Cursor) -> list:
        out = []
        try:
            while True:
                if self._cancelled:
                    raise QueryCancelled()
                rows = cur.fetchmany(FETCH_CHUNK)
                if not rows:
                    return out
                out.extend(rows)
        except sqlite3.OperationalError as exc:
            if "interrupt" in str(exc).lower() or self._cancelled:
                raise QueryCancelled() from exc
            raise

    def metric(self, mid: str) -> PlotMetric:
        return metric_by_id(self.info, mid)

    # -------------------------------------------------------------- population
    def population(self) -> dict:
        """N, not-evaluable count, element families with sizes, system sizes and blocks - one scan."""
        rows = self._fetchall(self._exec(
            f"SELECT r.family_id, r.block, COUNT(*), SUM(r.err != 0) FROM {self.frm} WHERE {self.where} "
            "GROUP BY r.family_id, r.block", self.params))
        fam_ids = {r[0] for r in rows if r[0] is not None}
        keys = {}
        if fam_ids:
            ids = sorted(fam_ids)
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                keys.update({fid: (key, size) for fid, key, size in self._exec(
                    f"SELECT family_id, key, size FROM families WHERE family_id IN ({','.join('?' * len(part))})",
                    part)})
        n = n_err = 0
        fams: dict[str, int] = {}
        sizes: dict[int, int] = {}
        blocks: dict[int, int] = {}
        for fid, block, cnt, errs in rows:
            n += cnt
            n_err += errs or 0
            if fid is not None:
                key, size = keys.get(fid, (None, None))
                fams[key] = fams.get(key, 0) + cnt
                sizes[size] = sizes.get(size, 0) + cnt
            if block is not None:
                blocks[block] = blocks.get(block, 0) + cnt
        families = sorted(((k, keys_size(k), c) for k, c in fams.items()), key=lambda t: (-t[2], t[0] or ""))
        return {"n": n, "n_error": n_err, "n_evaluated": n - n_err, "families": families,
                "sizes": dict(sorted(sizes.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))),
                "blocks": dict(sorted(blocks.items()))}

    def count(self) -> int:
        return self._exec(f"SELECT COUNT(*) FROM {self.frm} WHERE {self.where}", self.params).fetchone()[0]

    # -------------------------------------------------------------- statistics
    def statistics(self, metric_ids, exact_limit: int = EXACT_QUANTILE_MAX, group: str = DIM_NONE) -> dict:
        """Every measure of the Statistics table for ``metric_ids`` (see ``stats.py`` conventions).

        Returns ``{"n": population, "n_error": not evaluable, "exact": bool, "metrics": {id: {...}}}``;
        a metric's missing count is split by kind: ``missing_data`` / ``undefined`` / ``error``."""
        metrics = [self.metric(m) for m in metric_ids]
        if group != DIM_NONE:
            return self._grouped_statistics(metrics, group, exact_limit)
        design = any(m.needs_design for m in metrics)
        frm = self._from(design)
        first = [f"COUNT(*)", "SUM(r.err != 0)"]
        for m in metrics:
            und = f"SUM(r.err = 0 AND {m.sql} IS NULL AND ({m.undefined_sql}))" if m.undefined_sql else "0"
            first += [f"COUNT({m.sql})", f"AVG({m.sql})", f"MIN({m.sql})", f"MAX({m.sql})", und]
        row = self._exec(f"SELECT {', '.join(first)} FROM {frm} WHERE {self.where}", self.params).fetchone()
        n, n_err = row[0], row[1] or 0
        out: dict = {}
        sd_parts, sd_params = [], []
        for i, m in enumerate(metrics):
            cnt, avg, mn, mx, und = row[2 + 5 * i: 7 + 5 * i]
            und = und or 0
            errs = n_err
            out[m.id] = {"n_valid": cnt, "n_missing": n - cnt, "missing_data": max(0, n - cnt - und - errs),
                         "undefined": und, "error": errs, "mean": avg, "min": mn, "max": mx, "sd": None,
                         "q1": None, "median": None, "q3": None}
            sd_parts.append(f"SUM(({m.sql} - ?) * ({m.sql} - ?))")
            sd_params += [avg or 0.0, avg or 0.0]
        if metrics and n:
            ss = self._exec(f"SELECT {', '.join(sd_parts)} FROM {frm} WHERE {self.where}",
                            sd_params + self.params).fetchone()
            for m, s in zip(metrics, ss):
                c = out[m.id]["n_valid"]
                if c >= 2 and s is not None:
                    out[m.id]["sd"] = math.sqrt(max(0.0, s) / (c - 1))
        exact = True
        for m in metrics:
            c = out[m.id]["n_valid"]
            if not c:
                continue
            if c <= exact_limit:
                q1, med, q3 = self._quantiles_exact(m, c, frm, out[m.id]["min"], out[m.id]["max"])
            else:
                exact = False
                q1, med, q3, width = self._quantiles_binned(m, c, frm, out[m.id]["min"], out[m.id]["max"])
                out[m.id]["bin_width"] = width
            out[m.id].update(q1=q1, median=med, q3=q3)
        return {"n": n, "n_error": n_err, "exact": exact, "metrics": out}

    def _quantiles_exact(self, m: PlotMetric, n: int, frm: str, mn=None, mx=None) -> tuple:
        """Exact type-7 quartiles.  Two-pass selection (measured 1.7x faster than sorting every value at 1 M rows,
        ``design/implementation/performance.md``): one GROUP BY pass counts the values in ``APPROX_BINS`` equal bins,
        which locates the bin holding each needed rank; a second pass sorts only the values of those bins.  Both
        passes use the identical bin expression, so bin membership - and therefore every rank - is exact.  Values
        concentrated in a few bins (discrete descriptors such as VEC) or a non-finite range fall back to one sort
        of all values (``_quantiles_sorted``), which gives the same numbers."""
        need = {p: type7_positions(n, p) for p in QUARTILES}
        if mn is None or mx is None:
            return self._quantiles_sorted(m, n, frm, need)
        if mn == mx:
            return tuple(float(mn) for _p in QUARTILES)
        if not (math.isfinite(mn) and math.isfinite(mx)) or n < QUANTILE_SELECT_MIN:
            return self._quantiles_sorted(m, n, frm, need)
        nb = APPROX_BINS
        scale = nb / (mx - mn)
        bexpr = f"MIN({nb - 1}, CAST(({m.sql} - ?) * ? AS INTEGER))"
        counts = sorted(self._fetchall(self._exec(
            f"SELECT {bexpr} AS b, COUNT(*) FROM {frm} WHERE {self.where} AND {m.sql} IS NOT NULL GROUP BY b",
            [mn, scale] + self.params)))
        if sum(c for _b, c in counts) != n:
            return self._quantiles_sorted(m, n, frm, need)       # the population changed between the passes
        ranks = sorted({lo for lo, _h, _w in need.values()} | {hi for _l, hi, _w in need.values()})
        start: dict[int, int] = {}                # bin -> rank of its first value
        targets: list[int] = []
        cum = 0
        it = iter(ranks)
        r = next(it, None)
        for b, c in counts:
            if r is not None and r < cum + c:
                targets.append(b)
                start[b] = cum
                while r is not None and r < cum + c:
                    r = next(it, None)
            cum += c
        size = dict(counts)
        if sum(size[b] for b in targets) > n // 4:
            return self._quantiles_sorted(m, n, frm, need)
        # placeholders in textual order: bin expression (mn, scale) in the WHERE comes after the scope's own
        sql = (f"SELECT {m.sql} FROM {frm} WHERE {self.where} AND {m.sql} IS NOT NULL "
               f"AND {bexpr} IN ({','.join('?' * len(targets))}) ORDER BY {m.sql}")
        vals = [v for (v,) in self._fetchall(self._exec(sql, self.params + [mn, scale] + targets))]
        before: dict[int, int] = {}               # bin -> index of its first value in ``vals``
        acc = 0
        for b in targets:
            before[b] = acc
            acc += size[b]
        if acc != len(vals):
            return self._quantiles_sorted(m, n, frm, need)

        def at(rank: int):
            b = max(x for x in targets if start[x] <= rank)
            return vals[before[b] + rank - start[b]]
        return tuple(at(lo) + w * (at(hi) - at(lo)) for lo, hi, w in (need[p] for p in QUARTILES))

    def _quantiles_sorted(self, m: PlotMetric, n: int, frm: str, need: dict) -> tuple:
        """Exact type-7 quartiles from one sort of every value (ROW_NUMBER window)."""
        ranks = sorted({lo + 1 for lo, _h, _w in need.values()} | {hi + 1 for _l, hi, _w in need.values()})
        rows = self._fetchall(self._exec(
            f"SELECT rn, v FROM (SELECT {m.sql} AS v, ROW_NUMBER() OVER (ORDER BY {m.sql}) AS rn FROM {frm} "
            f"WHERE {self.where} AND {m.sql} IS NOT NULL) WHERE rn IN ({','.join('?' * len(ranks))})",
            self.params + ranks))
        at = {rn: v for rn, v in rows}
        res = []
        for p in QUARTILES:
            lo, hi, w = need[p]
            a, b = at.get(lo + 1), at.get(hi + 1)
            res.append(None if a is None or b is None else a + w * (b - a))
        return tuple(res)

    def _quantiles_binned(self, m: PlotMetric, n: int, frm: str, mn, mx) -> tuple:
        """Quartiles from APPROX_BINS equal bins (linear inside a bin); error at most one bin width."""
        if mn is None or mx is None or mx <= mn:
            return mn, mn, mn, 0.0
        width = (mx - mn) / APPROX_BINS
        counts = [0] * APPROX_BINS
        for b, c in self._fetchall(self._exec(
                f"SELECT MIN(CAST(({m.sql} - ?) / ? AS INTEGER), {APPROX_BINS - 1}), COUNT(*) FROM {frm} "
                f"WHERE {self.where} AND {m.sql} IS NOT NULL GROUP BY 1", [mn, width] + self.params)):
            counts[int(b)] = c
        res = []
        for p in QUARTILES:
            target = (n - 1) * p + 1
            acc = 0
            val = mx
            for i, c in enumerate(counts):
                if acc + c >= target:
                    frac = (target - acc) / c if c else 0.0
                    val = mn + (i + frac) * width
                    break
                acc += c
            res.append(val)
        return res[0], res[1], res[2], width

    def _grouped_statistics(self, metrics, group: str, exact_limit: int) -> dict:
        """Per group: N, median, Q1, Q3, min, max (box plots, family table)."""
        design = any(m.needs_design for m in metrics)
        frm = self._from(design, family=group == DIM_FAMILY)
        g = dim_sql(group)
        out: dict = {}
        for m in metrics:
            groups = {}
            for gv, cnt, mn, mx, avg in self._fetchall(self._exec(
                    f"SELECT {g}, COUNT({m.sql}), MIN({m.sql}), MAX({m.sql}), AVG({m.sql}) FROM {frm} "
                    f"WHERE {self.where} GROUP BY 1", self.params)):
                groups[gv] = {"n_valid": cnt, "min": mn, "max": mx, "mean": avg, "q1": None, "median": None,
                              "q3": None}
            sql = (f"SELECT g, n, rn, v FROM (SELECT {g} AS g, {m.sql} AS v, "
                   f"ROW_NUMBER() OVER (PARTITION BY {g} ORDER BY {m.sql}) AS rn, "
                   f"COUNT(*) OVER (PARTITION BY {g}) AS n FROM {frm} WHERE {self.where} AND {m.sql} IS NOT NULL) "
                   "WHERE " + " OR ".join(f"rn = 1 + CAST((n - 1) * {p} AS INTEGER) OR "
                                          f"rn = 2 + CAST((n - 1) * {p} AS INTEGER)" for p in QUARTILES))
            at: dict = {}
            for gv, n, rn, v in self._fetchall(self._exec(sql, self.params)):
                at.setdefault(gv, {})[rn] = v
                groups.setdefault(gv, {"n_valid": n})
            for gv, ranks in at.items():
                n = groups[gv]["n_valid"]
                vals = []
                for p in QUARTILES:
                    lo, hi, w = type7_positions(n, p)
                    a, b = ranks.get(lo + 1), ranks.get(hi + 1)
                    vals.append(None if a is None or b is None else a + w * (b - a))
                groups[gv].update(q1=vals[0], median=vals[1], q3=vals[2])
            out[m.id] = {k: groups[k] for k in dim_order(group, groups.keys())}
        return {"group": group, "exact": True, "metrics": out}

    # -------------------------------------------------------------- histogram
    def histogram(self, mid: str, bins: int | None = None, width: float | None = None) -> dict:
        m = self.metric(mid)
        frm = self._from(m.needs_design)
        n, n_valid, mn, mx = self._exec(
            f"SELECT COUNT(*), COUNT({m.sql}), MIN({m.sql}), MAX({m.sql}) FROM {frm} WHERE {self.where}",
            self.params).fetchone()
        if not n_valid:
            return {"metric": mid, "n": n, "n_valid": 0, "edges": [], "counts": []}
        if mx == mn:
            return {"metric": mid, "n": n, "n_valid": n_valid, "edges": [mn, mx], "counts": [n_valid], "width": 0.0}
        if width is None:
            width = nice_bin_width(mn, mx, bins or freedman_bins(n_valid))
        start = math.floor(mn / width) * width
        nb = max(1, int(math.ceil((mx - start) / width - 1e-9)))
        if start + nb * width <= mx:
            nb += 1
        counts = [0] * nb
        for b, c in self._fetchall(self._exec(
                f"SELECT MIN(MAX(CAST(({m.sql} - ?) / ? AS INTEGER), 0), {nb - 1}), COUNT(*) FROM {frm} "
                f"WHERE {self.where} AND {m.sql} IS NOT NULL GROUP BY 1", [start, width] + self.params)):
            counts[int(b)] = c
        return {"metric": mid, "n": n, "n_valid": n_valid, "edges": [start + i * width for i in range(nb + 1)],
                "counts": counts, "width": width}

    # -------------------------------------------------------------- model distributions
    def distribution(self, group: str = DIM_NONE) -> dict:
        """Per model: population, evaluated, N/A by kind, counts per class, class x status counts.

        Classes a model cannot produce are absent (never reported as zero)."""
        cols = []
        for k in MODEL_KEYS:
            cols += [f"r.{q(k)}", f"r.{q('status_' + k)}", f"r.{q('na_kind_' + k)}"]
        frm = self._from(family=group == DIM_FAMILY)
        gsql = dim_sql(group) if group != DIM_NONE else "NULL"
        rows = self._fetchall(self._exec(
            f"SELECT {gsql}, {', '.join(cols)}, COUNT(*) FROM {frm} WHERE {self.where} "
            f"GROUP BY 1, {', '.join(str(i + 2) for i in range(len(cols)))}", self.params))
        groups: dict = {}
        for row in rows:
            gv, cnt = row[0], row[-1]
            per = groups.setdefault(gv, {k: _empty_dist(k) for k in MODEL_KEYS})
            for j, k in enumerate(MODEL_KEYS):
                label, status, na = row[1 + 3 * j: 4 + 3 * j]
                d = per[k]
                d["population"] += cnt
                if label in (None, NA):
                    kind = NA_NAMES.get(na, NA_MISSING_DATA) if na is not None else (
                        NA_ERROR if label is None else NA_MISSING_DATA)
                    d["na"] += cnt
                    d["na_by_kind"][kind] = d["na_by_kind"].get(kind, 0) + cnt
                    continue
                d["evaluated"] += cnt
                d["classes"][label] = d["classes"].get(label, 0) + cnt
                sname = STATUS_NAMES.get(status, "in_domain") if status is not None else "in_domain"
                d["status"][sname] = d["status"].get(sname, 0) + cnt
                key = (label, sname)
                d["class_status"][key] = d["class_status"].get(key, 0) + cnt
        if group == DIM_NONE:
            return {"group": group, "models": groups.get(None, {k: _empty_dist(k) for k in MODEL_KEYS})}
        return {"group": group, "groups": {g: groups[g] for g in dim_order(group, groups.keys())}}

    # -------------------------------------------------------------- category counts
    def category_counts(self, dim: str) -> dict:
        frm = self._from(family=dim == DIM_FAMILY)
        rows = self._fetchall(self._exec(f"SELECT {dim_sql(dim)}, COUNT(*) FROM {frm} WHERE {self.where} GROUP BY 1",
                                         self.params))
        counts = dict(rows)
        return {k: counts[k] for k in dim_order(dim, counts.keys())}

    # -------------------------------------------------------------- scatter / sample / bins
    def valid_count(self, mids) -> tuple[int, int]:
        ms = [self.metric(m) for m in mids]
        frm = self._from(any(m.needs_design for m in ms))
        cond = " AND ".join(f"{m.sql} IS NOT NULL" for m in ms) or "1"
        n, valid = self._exec(f"SELECT COUNT(*), SUM({cond}) FROM {frm} WHERE {self.where}", self.params).fetchone()
        return n, valid or 0

    def points(self, x: str, y: str, color: str = DIM_NONE, *, budget: int = RAW_POINT_LIMIT,
               sample_target: int = SAMPLE_TARGET, force: str | None = None, seed: int = 1) -> dict:
        """Scatter data: RAW (every point) when the valid population fits ``budget``, else a SAMPLED
        subset (uniform, deterministic per result id and ``seed``) - never silently."""
        mx_, my_ = self.metric(x), self.metric(y)
        color_metric = None
        if color not in (DIM_NONE, "") and not _is_dim(color):
            color_metric = self.metric(color)
        need_design = mx_.needs_design or my_.needs_design or (color_metric is not None and color_metric.needs_design)
        frm = self._from(need_design, family=color == DIM_FAMILY)
        n, valid = self.valid_count([x, y])
        cond = f"{mx_.sql} IS NOT NULL AND {my_.sql} IS NOT NULL"
        rep = "RAW"
        where, params = f"{self.where} AND {cond}", list(self.params)
        if force == "SAMPLED" or (force is None and valid > budget):
            rep = "SAMPLED"
            if valid > sample_target:
                thr = int(_HASH_MOD * sample_target / valid)
                where += f" AND ((r.result_id * {_HASH_MUL} + {int(seed) * 97}) % {_HASH_MOD}) < ?"
                params.append(thr)
        csql = (color_metric.sql if color_metric else dim_sql(color)) if color not in (DIM_NONE, "") else "NULL"
        cur = self._exec(f"SELECT r.result_id, {mx_.sql}, {my_.sql}, {csql}, r.name FROM {frm} WHERE {where} "
                         "ORDER BY r.result_id", params)
        ids, xs, ys, cs, names = array("q"), array("d"), array("d"), [], []
        for row in self._fetchall(cur):
            ids.append(row[0])
            xs.append(row[1])
            ys.append(row[2])
            cs.append(row[3])
            names.append(row[4])
        out = {"representation": rep, "n": n, "n_valid": valid, "n_missing": n - valid, "n_shown": len(ids),
               "ids": ids, "x": xs, "y": ys, "color": color, "c": cs, "names": names,
               "seed": seed if rep == "SAMPLED" else None}
        if color not in (DIM_NONE, "") and _is_dim(color):
            out["category_counts"] = self.category_counts(color) if rep == "SAMPLED" else None
        return out

    def binned(self, x: str, y: str, bins: tuple[int, int] = (200, 200), value: str = DIM_NONE,
               xr: tuple | None = None, yr: tuple | None = None) -> dict:
        """2-D bins: count per cell, plus the majority class (categorical ``value``) or the mean of a metric."""
        mx_, my_ = self.metric(x), self.metric(y)
        vm = self.metric(value) if value not in (DIM_NONE, "") and not _is_dim(value) else None
        frm = self._from(mx_.needs_design or my_.needs_design or (vm is not None and vm.needs_design),
                         family=value == DIM_FAMILY)
        cond = f"{mx_.sql} IS NOT NULL AND {my_.sql} IS NOT NULL"
        n, valid, x0, x1, y0, y1 = self._exec(
            f"SELECT COUNT(*), SUM({cond}), MIN({mx_.sql}), MAX({mx_.sql}), MIN({my_.sql}), MAX({my_.sql}) "
            f"FROM {frm} WHERE {self.where}", self.params).fetchone()
        valid = valid or 0
        if xr:
            x0, x1 = xr
        if yr:
            y0, y1 = yr
        if not valid or x0 is None or y0 is None:
            return {"representation": "BINNED", "n": n, "n_valid": 0, "cells": [], "bins": bins,
                    "x": (x0, x1), "y": (y0, y1)}
        nx, ny = bins
        dx = (x1 - x0) / nx or 1.0
        dy = (y1 - y0) / ny or 1.0
        bx = f"MIN(MAX(CAST(({mx_.sql} - ?) / ? AS INTEGER), 0), {nx - 1})"
        by = f"MIN(MAX(CAST(({my_.sql} - ?) / ? AS INTEGER), 0), {ny - 1})"
        bp = [x0, dx, y0, dy]
        where = f"{self.where} AND {cond}"
        if vm is not None:
            sql = f"SELECT {bx}, {by}, COUNT(*), AVG({vm.sql}) FROM {frm} WHERE {where} GROUP BY 1, 2"
            cells = self._fetchall(self._exec(sql, bp + self.params))
        elif value not in (DIM_NONE, ""):
            v = dim_sql(value)
            sql = (f"SELECT bx, by, SUM(c) OVER (PARTITION BY bx, by), v, c FROM (SELECT {bx} AS bx, {by} AS by, "
                   f"{v} AS v, COUNT(*) AS c FROM {frm} WHERE {where} GROUP BY 1, 2, 3)")
            best: dict = {}
            for cx, cy, total, val, c in self._fetchall(self._exec(sql, bp + self.params)):
                cur = best.get((cx, cy))
                if cur is None or c > cur[2] or (c == cur[2] and str(val) < str(cur[1])):
                    best[(cx, cy)] = (total, val, c)
            cells = [(cx, cy, t, (val, c)) for (cx, cy), (t, val, c) in best.items()]
        else:
            cells = self._fetchall(self._exec(f"SELECT {bx}, {by}, COUNT(*), NULL FROM {frm} WHERE {where} GROUP BY 1, 2",
                                              bp + self.params))
        return {"representation": "BINNED", "n": n, "n_valid": valid, "n_missing": n - valid, "bins": bins,
                "x": (x0, x1), "y": (y0, y1), "cells": cells, "value": value}

    # -------------------------------------------------------------- ordered series / grids
    def series(self, x: str, ys, fixed: dict | None = None, tol: float = 1e-9, models: bool = True) -> dict:
        """Values along an ordered design axis ``x`` (other design variables fixed), ordered by x."""
        mx_ = self.metric(x)
        if not mx_.ordered:
            raise ValueError("A line plot needs an ordered axis")
        yms = [self.metric(y) for y in ys]
        frm = self._from(True)
        where, params = f"{self.where} AND {mx_.sql} IS NOT NULL", list(self.params)
        for name, value in (fixed or {}).items():
            where += f" AND abs({self.metric(name).sql} - ?) <= ?"
            params += [float(value), tol]
        cols = [f"r.result_id", "r.name", mx_.sql] + [m.sql for m in yms]
        if models:
            cols += [f"COALESCE(r.{q(k)}, '{NA}')" for k in MODEL_KEYS]
        rows = self._fetchall(self._exec(f"SELECT {', '.join(cols)} FROM {frm} WHERE {where} "
                                         f"ORDER BY {mx_.sql}, r.result_id", params))
        k = len(yms)
        return {"x": [r[2] for r in rows], "ids": [r[0] for r in rows], "names": [r[1] for r in rows],
                "y": {y: [r[3 + i] for r in rows] for i, y in enumerate(ys)},
                "labels": {mk: [r[3 + k + j] for r in rows] for j, mk in enumerate(MODEL_KEYS)} if models else {},
                "duplicates": len(rows) - len({r[2] for r in rows})}

    def grid(self, x: str, y: str, value: str, fixed: dict | None = None, tol: float = 1e-9) -> dict:
        """Two-parameter heatmap cells.  ``complete`` is true only if every (x, y) of the grid has exactly
        one result; otherwise the caller must switch to a labelled binned heatmap."""
        mx_, my_ = self.metric(x), self.metric(y)
        if not (mx_.ordered and my_.ordered):
            raise ValueError("A heatmap needs two design axes")
        frm = self._from(True)
        cat = _is_dim(value)
        vsql = dim_sql(value) if cat else self.metric(value).sql
        where, params = f"{self.where} AND {mx_.sql} IS NOT NULL AND {my_.sql} IS NOT NULL", list(self.params)
        for name, v in (fixed or {}).items():
            where += f" AND abs({self.metric(name).sql} - ?) <= ?"
            params += [float(v), tol]
        rows = self._fetchall(self._exec(
            f"SELECT {mx_.sql}, {my_.sql}, {vsql}, r.result_id, r.name FROM {frm} WHERE {where} "
            f"ORDER BY {my_.sql}, {mx_.sql}", params))
        xs = sorted({_round(r[0]) for r in rows})
        ys = sorted({_round(r[1]) for r in rows})
        cells: dict = {}
        multi = 0
        for xv, yv, v, rid, name in rows:
            key = (_round(xv), _round(yv))
            if key in cells:
                multi += 1
            cells[key] = (v, rid, name)
        complete = multi == 0 and len(cells) == len(xs) * len(ys)
        return {"xs": xs, "ys": ys, "cells": cells, "complete": complete, "multiple": multi,
                "missing_cells": len(xs) * len(ys) - len(cells), "value": value, "categorical": cat,
                "n": len(rows)}

    def run_counts(self, run_ids) -> dict[int, int]:
        """Alive results per run in the table's workspace (the Run selector's counts)."""
        return {rid: self._exec("SELECT COUNT(*) FROM results WHERE run_id=? AND result_id >= ?",
                                (rid, self.lo)).fetchone()[0] for rid in run_ids}

    # -------------------------------------------------------------- ids
    def ids(self, limit: int | None = None) -> list[int]:
        sql = f"SELECT r.result_id FROM {self.frm} WHERE {self.where} ORDER BY r.result_id"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [r[0] for r in self._fetchall(self._exec(sql, self.params))]


# ====================================================================== helpers
def keys_size(key: str | None) -> int | None:
    return None if not key else key.count("-") + 1


def _is_dim(name: str) -> bool:
    return name in (DIM_FAMILY, DIM_SIZE, DIM_BLOCK, DIM_CSTR) or name.startswith(("model:", "status:"))


def is_dimension(name: str) -> bool:
    return _is_dim(name)


def _round(v: float) -> float:
    return round(v, 9)


def _empty_dist(model: str) -> dict:
    return {"model": model, "population": 0, "evaluated": 0, "na": 0, "na_by_kind": {}, "classes": {},
            "status": {}, "class_status": {}}


def freedman_bins(n: int) -> int:
    """Sturges-like default bin count bounded to 10..60."""
    return max(10, min(60, int(math.ceil(math.log2(max(n, 1)) + 1)) * 2))


def nice_bin_width(lo: float, hi: float, target_bins: int) -> float:
    """A 1 / 2 / 2.5 / 5 × 10^k bin width giving about ``target_bins`` bins."""
    span = hi - lo
    if span <= 0:
        return 1.0
    raw = span / max(1, target_bins)
    k = math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        w = m * 10 ** k
        if w >= raw:
            return w
    return 10 ** (k + 1)


_ = (NA_CODES, STATUS_CODES, NA_UNDEFINED, decimals_for)
