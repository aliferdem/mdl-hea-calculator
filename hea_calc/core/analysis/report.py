"""Scientific reports of the current Analysis state - Composition and Collection (no Qt).

The report content is HTML in a neutral, printable light theme (black text on white, whatever the
application theme), rendered to PDF by ``ui/analysis/report_ui.py`` (QTextDocument + QPdfWriter: selectable,
searchable text; equations as text; tables with repeated header rows; explicit page breaks).

Nothing is recalculated here: a Composition report formats one engine result (the stored inputs reproduced
by the engine with the run's settings - the same result Analysis shows); a Collection report formats the
answers of the Analysis query layer for the resolved scope.  A sampled plot is always labelled as a sample of
its population.
"""

from __future__ import annotations

import datetime as _dt
import html as _h
import re

from ... import __version__ as APP_VERSION
from ..composition import from_fractions, name_html
from ..engine import MODEL_KEYS, MODELS, NA, STATUS_DATA_SUSPECT, STATUS_EXTRAPOLATED
from ..family import family_key
from ..provenance import DATASET_LABELS
from . import models as MD
from .metrics import DESCRIPTORS, DESCRIPTORS_LIST, GROUPS, KEY_DESCRIPTORS, format_value, full_precision

# Light print palette (Carbon g10 tag colours: they encode scientific classes, as in the application).
TAG_PRINT = {"SS": ("#a7f0ba", "#0e6027"), "MP": ("#ffd6e8", "#9f1853"), "IM": ("#ffd7d9", "#a2191f"),
             "SS+IM": ("#d0e2ff", "#0043ce"), "MG": ("#e8daff", "#6929c4"), NA: ("#e0e0e0", "#161616"),
             "FCC": ("#dde1e6", "#343a3f"), "BCC": ("#dde1e6", "#343a3f"), "BCC + FCC": ("#dde1e6", "#343a3f")}

CSS = """
body { color: #161616; background: #ffffff; font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; font-size: 9.5pt; }
h1 { font-size: 18pt; font-weight: 400; margin: 0 0 4px 0; }
h2 { font-size: 12.5pt; font-weight: 600; margin: 16px 0 6px 0; color: #161616; }
h3 { font-size: 10.5pt; font-weight: 600; margin: 10px 0 4px 0; }
p { margin: 0 0 6px 0; }
.meta { color: #525252; font-size: 8.5pt; }
.note { color: #525252; font-size: 8.5pt; }
.warn { color: #8e6a00; }
table { border-collapse: collapse; margin: 4px 0 8px 0; }
th { background: #e0e0e0; color: #161616; font-weight: 600; text-align: left; padding: 3px 6px; border: 1px solid #c6c6c6; }
td { padding: 3px 6px; border: 1px solid #c6c6c6; vertical-align: top; }
td.num { text-align: right; }
.group td { background: #f4f4f4; font-weight: 600; }
.tag { font-weight: 600; }
"""

LIMITATIONS = [
    "All eight criteria are empirical or semi-empirical screening rules calibrated on limited sets of mostly "
    "as-cast or annealed alloys; they predict tendencies, not phase diagrams.",
    "Different criteria use different radius sets, binary datasets and temperatures; their numbers are not "
    "interchangeable (δ for M2 is not δ<sub>CN12</sub> for M1; φ of M5 is unrelated to Φ of M8).",
    "MP means “not a single solid solution”; it does not identify the phases.",
    "Binary data refer to binary systems only; ternary and higher compounds are not considered.",
    "Element coverage of a model does not imply the model was validated for alloys of those elements.",
    "Rule-of-mixtures T<sub>m</sub> and density ignore excess quantities.",
]

MODE_NAMES = {"single": "Single composition", "sweep": "Composition space", "expression": "Composition expression",
              "import": "Imported compositions"}

_SUP = {"⁻": "−", "¹": "1", "²": "2", "³": "3", "⁰": "0", "⁴": "4"}


def sup(text: str) -> str:
    """Unicode superscripts as HTML <sup> (fonts embedded in a PDF may lack ⁻ ¹)."""
    out, run = [], ""
    for ch in text or "":
        if ch in _SUP:
            run += _SUP[ch]
            continue
        if run:
            out.append(f"<sup>{run}</sup>")
            run = ""
        out.append(ch)
    if run:
        out.append(f"<sup>{run}</sup>")
    return "".join(out)


def tag(label: str) -> str:
    bg, fg = TAG_PRINT.get(label, TAG_PRINT[NA])
    return f"<span class='tag' style='background:{bg}; color:{fg};'>&nbsp;{_h.escape(label)}&nbsp;</span>"


def _e(text) -> str:
    return _h.escape(str(text if text is not None else ""))


def now_text() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def safe_filename(text: str, prefix: str = "HEA_Analysis_", ext: str = ".pdf", max_len: int = 120) -> str:
    """A Windows/macOS/Linux-safe file name: ``HEA_Analysis_CoCrFeMnNi.pdf``, ``HEA_Analysis_Run_3.pdf``."""
    body = re.sub(r"[^A-Za-z0-9._-]+", "_", text or "").strip("._-") or "report"
    body = re.sub(r"_+", "_", body)
    name = (prefix + body)[: max_len - len(ext)].rstrip("._-")
    stem = name.split(".")[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return name + ext


def _settings_rows(info) -> list[tuple[str, str]]:
    rows = []
    if info is None:
        return rows
    st = info.settings or {}
    if st.get("annealing_temperature"):
        rows.append(("M6/M7 temperature", f"annealing temperature {st['annealing_temperature']:g} K (user setting)"))
    else:
        rows.append(("M6/M7 temperature", f"{st.get('tcrit_fraction', 0.55):g}·T<sub>m</sub> (no annealing temperature set)"))
    return rows


def _provenance_rows(info) -> list[tuple[str, str]]:
    rows = []
    if info is None:
        return [("Calculation run", "not stored (snapshot)")]
    rows.append(("Calculation run", f"Run {info.run_id} · {MODE_NAMES.get(info.mode, info.mode)} · status {info.status}"))
    if info.created:
        rows.append(("Calculated", info.created.replace("T", " ")))
    rows += _settings_rows(info)
    rows.append(("Engine version", _e(info.engine_version or "not stored")))
    rows.append(("Calculator version", _e(info.app_version or "not stored")))
    for name, ident in (info.dataset_ids or {}).items():
        rows.append((_e(DATASET_LABELS.get(name, name)), _e(ident)))
    return rows


def kv_table(rows) -> str:
    return "<table width='100%'>" + "".join(f"<tr><td width='34%'>{k}</td><td>{v}</td></tr>" for k, v in rows) + \
        "</table>"


def table(headers, rows, widths=None, num_cols=()) -> str:
    """HTML table with a header row (repeated on every PDF page by the renderer)."""
    w = widths or [None] * len(headers)
    head = "".join(f"<th{f' width={x}%' if x else ''}>{h}</th>" for h, x in zip(headers, w))
    body = []
    for r in rows:
        if isinstance(r, tuple) and r and r[0] == "__group__":
            body.append(f"<tr class='group'><td colspan='{len(headers)}'>{r[1]}</td></tr>")
            continue
        body.append("<tr>" + "".join(f"<td class='num'>{c}</td>" if i in num_cols else f"<td>{c}</td>"
                                     for i, c in enumerate(r)) + "</tr>")
    return f"<table width='100%'><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _header(title: str, subtitle: str, created: str) -> str:
    return (f"<h1>{_e(title)}</h1><p class='meta'>HEA Calculator {APP_VERSION} · report created {created}</p>"
            f"<p>{subtitle}</p>")


# ====================================================================== composition report
def _grams(g: float) -> str:
    s = f"{g:.4f}".rstrip("0").rstrip(".")
    return s or f"{g:.4g}"


def composition_report_html(row, info=None, created: str | None = None, batch_mass: float = 2.0) -> str:
    """Complete Composition report for one engine result (``ResultRow``).  ``batch_mass`` (g) is the user's Total
    mass preference: the element masses of that batch are derived from the atomic fractions (display only)."""
    created = created or now_text()
    res = row.result
    parts = [f"<html><head><style>{CSS}</style></head><body>"]
    parts.append(_header("Composition report", f"<b>{name_html(row.name)}</b>", created))
    if not res.ok:
        parts.append(f"<p class='warn'>This composition could not be evaluated: {_e(res.error)}</p></body></html>")
        return "".join(parts)
    d = res.descriptors
    comp = res.composition
    reps = {rep: from_fractions(dict(comp), rep) for rep in ("ratio", "at", "wt")}
    batch = batch_mass if batch_mass and batch_mass > 0 else 2.0
    reps["mass"] = from_fractions(dict(comp), "mass", total_mass=batch)
    parts.append("<h2>Composition</h2>")
    parts.append(kv_table([("Alloy", name_html(row.name)), ("Element family", _e(family_key(comp))),
                           ("Number of elements", str(len(comp)))] +
                          ([("Expression variables", ", ".join(f"<i>{_e(k)}</i> = {v:g}"
                                                                for k, v in row.variables.items()))]
                           if getattr(row, "variables", None) else [])))
    parts.append(table(["Element", "at.%", "At. ratio", "wt.%", f"Mass ({_grams(batch)} g batch)"],
                       [[el, f"{reps['at'][el]:.2f}", f"{reps['ratio'][el]:.3f}", f"{reps['wt'][el]:.2f}",
                         f"{reps['mass'][el]:.4f}"] for el in comp], [16, 18, 18, 18, 30], num_cols=(1, 2, 3, 4)))
    parts.append(f"<p class='note'>Masses: the element masses of a {_grams(batch)} g batch of this composition "
                 "(standard atomic weights; the batch mass is a display preference and does not affect any "
                 "calculated value).</p>")
    parts.append("<h2>Calculation and provenance</h2>")
    prov = _provenance_rows(info)
    if res.temperature is not None:
        prov.insert(1, ("Assessment temperature (M6, M7)",
                        f"{res.temperature:.1f} K ({_e(res.temperature_source or '')})"))
    parts.append(kv_table(prov))
    parts.append("<h2>Key descriptors</h2>")
    key_rows = []
    for k in KEY_DESCRIPTORS:
        dd = DESCRIPTORS[k]
        key_rows.append([f"{dd.name}", dd.symbol, _val(d, k), sup(dd.unit) or "–"])
    key_rows.append(["Crystal structure (VEC rule)", "–", tag(d.get("cstr") or NA), "–"])
    parts.append(table(["Descriptor", "Symbol", "Value", "Unit"], key_rows, [44, 16, 20, 20], num_cols=(2,)))
    parts.append("<p class='note'>Crystal structure by the VEC rule of Guo et al. (2011): FCC if VEC ≥ 8.0, BCC if "
                 "VEC &lt; 6.87, otherwise BCC + FCC. A tendency, not an observed phase.</p>")
    parts.append("<h2>Model predictions</h2>")
    mrows = []
    for k in MODEL_KEYS:
        o = res.models[k]
        status = ("Not available — " + ("undefined" if o.na_kind == "undefined" else "missing data")) \
            if o.label == NA else MD.STATUS_LABELS.get(o.status, o.status)
        mrows.append([_e(MD.title(k)), tag(o.label), _e(status), sup(MD.criterion_value_text(k, d, o.label)),
                      sup(MD.threshold_text(k, d))])
    parts.append(table(["Model", "Prediction", "Status", "Criterion value", "Threshold (solid solution)"], mrows,
                       [22, 12, 17, 25, 24]))
    notes = []
    for k in MODEL_KEYS:
        o = res.models[k]
        if o.label == NA and o.reason:
            notes.append(f"<b>{k} not available.</b> {_e(o.reason)} Missing data are not replaced by zero.")
        if o.label != NA and o.caution:
            kind = {STATUS_DATA_SUSPECT: "Flagged binary data", STATUS_EXTRAPOLATED: "Extrapolated"}.get(o.status,
                                                                                                        "Caution")
            notes.append(f"<b>{k} · {kind}.</b> {_e(o.caution)}")
    if notes:
        parts.append("<h3>Not-available reasons and cautions</h3>" + "".join(f"<p>{n}</p>" for n in notes))
    parts.append("<h2>Data quality</h2>")
    if res.warnings or notes:
        parts += [f"<p class='warn'>{_e(w)}</p>" for w in res.warnings]
        if not res.warnings:
            parts.append("<p>See the model notes above.</p>")
    else:
        parts.append("<p>All required data available. No cautions.</p>")
    parts.append("<h2 style='page-break-before: always;'>Complete descriptor table</h2>")
    drows = []
    for g in GROUPS:
        drows.append(("__group__", _e(g)))
        for dd in DESCRIPTORS_LIST:
            if dd.group != g:
                continue
            name = dd.name + (f" ({_e(d[dd.pair_key])})" if dd.pair_key and d.get(dd.pair_key) else "")
            val = tag(d.get("cstr") or NA) if dd.key == "cstr" else _val(d, dd.key)
            exact = full_precision(d.get(dd.key)) if isinstance(d.get(dd.key), float) else ""
            drows.append([name, dd.symbol or "–", val, sup(dd.unit) or "–", exact])
    parts.append(table(["Descriptor", "Symbol", "Value", "Unit", "Full precision"], drows, [36, 12, 14, 16, 22],
                       num_cols=(2, 4)))
    parts.append("<h2>Definitions</h2>")
    for dd in DESCRIPTORS_LIST:
        if dd.equation:
            parts.append(f"<p><b>{dd.name}</b> — {dd.equation}. <span class='note'>Data: {_e(dd.data)}."
                         f"{' ' + dd.undefined if dd.undefined else ''}</span></p>")
    parts.append("<h2 style='page-break-before: always;'>Model criteria and references</h2>")
    for k in MODEL_KEYS:
        h = MD.HELP[k]
        parts.append(f"<h3>{_e(MD.title(k))} — {_e(MODELS[k].name.replace('<sub>', '').replace('</sub>', '')) if MODELS[k].name else ''}</h3>")
        parts.append(f"<p><b>Criterion.</b> {_e(MODELS[k].criterion)}</p>")
        parts.append(f"<p><b>Purpose.</b> {h.purpose}</p><p><b>Data.</b> {h.data}</p>"
                     f"<p><b>Not available when</b> {h.not_available[0].lower() + h.not_available[1:]}</p>"
                     f"<p><b>Limitations.</b> {sup(h.limitations)}</p>")
        parts.append(f"<p class='note'>{_e(MODELS[k].reference)}</p>")
    parts.append("<h2>Scientific limitations</h2>" + "".join(f"<p>• {x}</p>" for x in LIMITATIONS))
    parts.append("</body></html>")
    return "".join(parts)


def _val(d: dict, key: str) -> str:
    v = d.get(key)
    if v is None:
        return "Undefined" if d.get(f"{key}_undefined") else "N/A"
    return _e(format_value(key, v))


# ====================================================================== collection report
def collection_report_html(ctx: dict, created: str | None = None) -> str:
    """Collection report from Analysis query answers.

    ``ctx``: ``scope`` (CollectionScope), ``info`` (RunInfo), ``population`` (query), ``stats`` (query),
    ``distribution`` (query), ``plot`` (``{"image": resource name, "title", "x", "y", "colour", "representation",
    "shown", "population", "n_missing", "caption"}`` or None), ``filters_text``, ``stale`` (str|None),
    ``run_count`` (results of the run)."""
    created = created or now_text()
    sc, info = ctx["scope"], ctx["info"]
    pop, stats, dist = ctx["population"], ctx["stats"], ctx["distribution"]
    from .scope import BASE_LABELS
    parts = [f"<html><head><style>{CSS}</style></head><body>"]
    title = f"Run {sc.run_id} · {MODE_NAMES.get(info.mode, info.mode) if info else ''}"
    parts.append(_header("Collection analysis report", f"<b>{_e(title)}</b>", created))
    parts.append("<h2>Collection</h2>")
    rows = [("Calculation run", _e(title)), ("Population", _e(BASE_LABELS[sc.base]))]
    if sc.base == "filtered":
        rows.append(("Results-table filter (copy)", _e(ctx.get("filters_text") or "none")))
    if sc.families:
        rows.append(("Restriction: element family", _e(", ".join(sc.families))))
    if sc.sizes:
        rows.append(("Restriction: system size", _e(", ".join(str(s) for s in sc.sizes)) + " elements"))
    if sc.blocks:
        rows.append(("Restriction: expression block", _e(", ".join(str(b + 1) for b in sc.blocks))))
    rows += [("Analysed results", f"{pop['n']:,} of {ctx.get('run_count', pop['n']):,} results of the run"),
             ("Evaluated / not evaluable", f"{pop['n_evaluated']:,} / {pop['n_error']:,}")]
    parts.append(kv_table(rows))
    if ctx.get("stale"):
        parts.append(f"<p class='warn'><b>Collection out of date.</b> {_e(ctx['stale'])} The values in this report "
                     "refer to the collection as resolved, not to the current table state.</p>")
    if info is not None and info.status != "complete":
        verb = {"running": "is still calculating", "cancelled": "was cancelled", "failed": "failed",
                "interrupted": "was interrupted"}.get(info.status, info.status)
        parts.append(f"<p class='warn'><b>Partial run.</b> This run {verb}: {info.calculated:,} of "
                     f"{info.expected or info.calculated:,} compositions were stored. The report describes the stored "
                     "results only.</p>")
    parts.append("<h2>Calculation and provenance</h2>")
    parts.append(kv_table(_provenance_rows(info)))
    parts.append("<h2>Population</h2>")
    n = max(1, pop["n"])
    parts.append("<h3>System size</h3>")
    parts.append(table(["System size", "Results", "Share"],
                       [[f"{s} elements" if s is not None else "Not evaluable", f"{c:,}", f"{100 * c / n:.2f} %"]
                        for s, c in pop["sizes"].items()], [40, 30, 30], num_cols=(1, 2)))
    parts.append(f"<p class='note'>Denominator: {pop['n']:,} results in the collection.</p>")
    parts.append("<h3>Element families</h3>")
    fams = pop["families"]
    frows = [[_e(k or "Not evaluable"), f"{c:,}", f"{100 * c / n:.2f} %"] for k, _s, c in fams[:200]]
    if len(fams) > 200:
        rest = sum(c for _k, _s, c in fams[200:])
        frows.append([f"Other families ({len(fams) - 200:,})", f"{rest:,}", f"{100 * rest / n:.2f} %"])
    parts.append(table(["Element family", "Results", "Share"], frows, [50, 25, 25], num_cols=(1, 2)))
    if stats is not None:
        parts.append("<h2 style='page-break-before: always;'>Descriptive statistics</h2>")
        srows = []
        for k, m in stats["metrics"].items():
            dd = DESCRIPTORS.get(k)
            name = f"{dd.symbol} ({sup(dd.unit) or '–'})" if dd else _e(k)

            def f(v, kk=k):
                return "—" if v is None else _e(format_value(kk, v))
            srows.append([name, f"{m['n_valid']:,}", f"{m['n_missing']:,}", f(m["mean"]), f(m["sd"]), f(m["min"]),
                          f(m["q1"]), f(m["median"]), f(m["q3"]), f(m["max"])])
        parts.append(table(["Metric", "N valid", "N missing", "Mean", "SD", "Min", "Q1", "Median", "Q3", "Max"], srows,
                           [19, 8, 9, 9, 8, 9, 9, 10, 9, 10], num_cols=tuple(range(1, 10))))
        focus = ctx.get("focus")
        if focus and focus in DESCRIPTORS:
            fd = DESCRIPTORS[focus]
            parts.append(f"<p class='note'>Selected distribution metric in Analysis: {fd.symbol} — {_e(fd.name)} "
                         f"({sup(fd.unit) or '–'}).  No metric is singled out by the calculator itself.</p>")
        exact = "exact" if stats.get("exact") else "approximate (binned; error at most one bin width)"
        parts.append(f"<p class='note'>N = {stats['n']:,} results in scope. N/A values are excluded and counted under "
                     "N missing (missing data, undefined and not evaluable). Sample standard deviation (n − 1); "
                     f"quartiles by linear interpolation between ordered values (Hyndman–Fan type 7); {exact}.</p>")
    if dist is not None:
        models = dist["models"]
        parts.append("<h2 style='page-break-before: always;'>Model coverage and distributions</h2>")
        cov = [[_e(MD.title(k)), f"{models[k]['population']:,}", f"{models[k]['evaluated']:,}", f"{models[k]['na']:,}",
                _e(", ".join(f"{kk.replace('_', ' ')} {v:,}" for kk, v in models[k]["na_by_kind"].items()) or "—")]
               for k in MODEL_KEYS]
        parts.append(table(["Model", "Population", "Evaluated", "Not available", "Not-available reasons"], cov,
                           [28, 14, 14, 14, 30], num_cols=(1, 2, 3)))
        for k in MODEL_KEYS:
            m = models[k]
            e = m["evaluated"]
            rows_k = []
            for cls in MD.CLASSES[k]:
                c = m["classes"].get(cls, 0)
                st_parts = ", ".join(f"{s.replace('_', ' ')} {v:,}" for (c_, s), v in m["class_status"].items()
                                     if c_ == cls)
                rows_k.append([tag(cls), f"{c:,}", f"{100 * c / e:.1f} %" if e else "—",
                               f"{100 * c / m['population']:.1f} %" if m["population"] else "—", _e(st_parts or "—")])
            rows_k.append([tag(NA), f"{m['na']:,}", "—", f"{100 * m['na'] / m['population']:.1f} %"
                           if m["population"] else "—", "—"])
            parts.append(f"<h3>{_e(MD.title(k))}</h3>")
            parts.append(table(["Class", "Results", f"% of evaluated ({e:,})",
                                f"% of population ({m['population']:,})", "Evidence status"], rows_k,
                               [16, 14, 22, 22, 26], num_cols=(1, 2, 3)))
        parts.append("<p class='note'>Classes differ between models; a class a model cannot produce is not listed "
                     "(it is not a zero count). Not-available results are counted separately and are excluded from "
                     "the “% of evaluated” denominator.</p>")
    plot = ctx.get("plot")
    if plot:
        parts.append("<h2 style='page-break-before: always;'>Plot</h2>")
        parts.append(f"<p><b>{plot['title']}</b></p>")
        parts.append(f"<p><img src='{plot['image']}' width='{plot.get('width', 640)}'></p>")
        prow = [("Plot type", _e(plot.get("type", ""))), ("X axis", plot.get("x", "")), ("Y axis", plot.get("y", "")),
                ("Colour / grouping", plot.get("colour", "")), ("Representation", _e(plot["representation"]))]
        if plot.get("sampled"):
            prow.append(("Sample", f"{plot['shown']:,} of {plot['population']:,} points drawn (uniform, fixed seed); "
                                   "statistics and counts in this report use all results, not the sample."))
        prow.append(("Omitted (no value)", f"{plot.get('n_missing', 0):,}"))
        parts.append(kv_table(prow))
    parts.append("<h2>Scientific limitations</h2>" + "".join(f"<p>• {x}</p>" for x in LIMITATIONS))
    parts.append("</body></html>")
    return "".join(parts)
