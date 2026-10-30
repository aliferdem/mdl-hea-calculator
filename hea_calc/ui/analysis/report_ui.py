"""Export report (PDF), print, and Analysis data / plot exports - the Qt side.

* :class:`ReportTask` prepares a report on a worker ``QThread``: the repository queries (own read-only
  connection), the HTML (``core/analysis/report.py``) and the PDF (``QTextDocument`` laid out on a
  ``QPdfWriter``: A4, selectable text, header rows repeated on each page, page numbers).  Only the plot image
  is rendered on the GUI thread beforehand (from the plot on screen, so the report shows what was analysed).
  The GUI stays responsive; the task can be cancelled; one finished signal, delivered queued to the GUI thread.
  It must be a ``QThread``: ``QTextDocument``'s layout starts a ``QBasicTimer`` (``setHtml``, ``setPageSize``,
  ``pageCount``), which Qt refuses - with "QBasicTimer can only be used with threads started with QThread" - in a
  plain Python thread (it was 9 warnings per composition report, 6 per collection report).
* Plot exports (SVG / PNG) render the visible plot through the same painter; data exports stream the
  query answers already on screen with a ``#`` provenance header.
"""

from __future__ import annotations

import csv
import threading
from pathlib import Path

from PySide6.QtCore import QMarginsF, QObject, QSizeF, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QFont, QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import QFileDialog

from ...core.analysis import report as R
from ...core.analysis.metrics import DESCRIPTORS, STATS_DEFAULT
from ...core.analysis.plotting import SAMPLED
from ...core.analysis.scope import filter_text

PAGE_MARGINS_MM = (16, 16, 16, 18)


class ReportCancelled(Exception):
    pass


def render_pdf(html: str, path: str, resources: dict | None = None, title: str = "HEA Calculator report") -> int:
    """Render report HTML to an A4 PDF; returns the page count.  Safe on a worker thread (no widgets).

    The document is laid out on the PDF device itself (300 dpi, point sizes exact) with the page body size,
    so table header rows repeat on every page and the page count is known; each page is drawn with a footer
    "<title>, page i of n".  Text stays text (selectable, searchable)."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QPainter
    writer = QPdfWriter(path)
    writer.setTitle(title)
    writer.setCreator(R.BRAND)
    writer.setResolution(300)
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                     QMarginsF(*PAGE_MARGINS_MM), QPageLayout.Unit.Millimeter))
    doc = QTextDocument()
    doc.documentLayout().setPaintDevice(writer)
    doc.setDefaultFont(QFont("IBM Plex Sans", 9))
    doc.setDocumentMargin(0)
    for name, img in (resources or {}).items():
        doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), img)
    doc.setHtml(html)
    w, h = writer.width(), writer.height()
    footer_h = int(writer.resolution() * 0.28)
    body_h = h - footer_h
    doc.setPageSize(QSizeF(w, body_h))
    n = max(1, doc.pageCount())
    p = QPainter(writer)
    try:
        foot_font = QFont("IBM Plex Sans", 7)
        for i in range(n):
            if i:
                writer.newPage()
            p.save()
            p.translate(0, -i * body_h)
            doc.drawContents(p, QRectF(0, i * body_h, w, body_h))
            p.restore()
            p.setFont(foot_font)
            p.setPen(QColor("#525252"))
            p.drawText(QRectF(0, h - footer_h * 0.7, w, footer_h * 0.7),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), f"{title}, page {i + 1} of {n}")
            p.drawText(QRectF(0, h - footer_h * 0.7, w, footer_h * 0.7),          # report identity (left)
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), R.BRAND)
    finally:
        p.end()
    return n


class _ReportThread(QThread):
    """Runs one report job (see the module docstring for why this is a QThread, not a Python thread)."""

    done = Signal(str, object)                          # status, value - queued to the task (GUI thread)

    def __init__(self, task: "ReportTask", fn, args):
        super().__init__()
        self.setObjectName("hea-report")
        self.task, self.fn, self.args = task, fn, args

    def run(self) -> None:
        task = self.task
        try:
            value = self.fn(task, *self.args)
            status = "cancelled" if task._cancel.is_set() else "ok"
        except ReportCancelled:
            status, value = "cancelled", None
        except Exception as exc:                        # noqa: BLE001 - reported to the user
            from ...core.analysis.queries import QueryCancelled
            if isinstance(exc, QueryCancelled):
                status, value = "cancelled", None
            else:
                status, value = "error", str(exc)
        self.done.emit(status, value)


class ReportTask(QObject):
    """Latest-wins background report generation; ``finished(status, value)`` (ok/cancelled/error) on the GUI
    thread.  The worker is a :class:`QThread` owned here: it is joined when it ends and on :meth:`shutdown`."""

    finished = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = threading.Event()
        self._thread: _ReportThread | None = None
        self._sq = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self, fn, *args) -> None:
        """Run ``fn(task, *args) -> value`` on a worker QThread."""
        self._cancel.clear()
        old = self._thread
        if old is not None and old.isRunning():
            old.done.disconnect()                       # a superseded job never delivers
            self._cancel.set()
            old.wait(3000)
            self._cancel.clear()
        th = _ReportThread(self, fn, args)
        th.done.connect(self._delivered, Qt.ConnectionType.QueuedConnection)
        th.finished.connect(th.deleteLater)
        self._thread = th
        th.start()

    def _delivered(self, status: str, value) -> None:
        th = self.sender()
        if th is not None and th is not self._thread:
            return
        if th is not None:
            th.wait(1000)                               # run() has returned: join before reporting
        self._thread = None
        self.finished.emit(status, value)

    def shutdown(self, timeout_ms: int = 3000) -> None:
        """Cancel and join a running job (window close)."""
        th = self._thread
        if th is not None and th.isRunning():
            self.cancel()
            th.wait(timeout_ms)

    def cancel(self) -> None:
        self._cancel.set()
        if self._sq is not None:
            self._sq.cancel()

    def check(self) -> None:
        if self._cancel.is_set():
            raise ReportCancelled()


# ====================================================================== composition
def _batch_mass(win) -> float:
    """The Total mass preference of the window (Mass column of composition reports)."""
    while win is not None:
        prefs = getattr(win, "prefs", None)
        if prefs is not None:
            return prefs.total_mass
        win = win.parent() if hasattr(win, "parent") else None
    from ..preferences import DEFAULT_TOTAL_MASS
    return DEFAULT_TOTAL_MASS


def _composition_job(task: ReportTask, row, info, path: str, batch_mass: float = 2.0) -> dict:
    html = R.composition_report_html(row, info, batch_mass=batch_mass)
    task.check()
    pages = render_pdf(html, path, title=f"Composition report – {row.name}")
    return {"path": path, "pages": pages}


# ====================================================================== collection
def _collection_job(task: ReportTask, repo, scope, info, workspace_lo: int, metrics, plot, stale, run_count,
                    filters_text, path: str, focus: str = "", run_counts: dict | None = None) -> dict:
    from ...core.analysis.queries import ScopeQuery
    con = repo.reader_connection()
    try:
        sq = ScopeQuery(con, scope, info, workspace_lo)
        task._sq = sq
        pop = sq.population()
        task.check()
        stats = sq.statistics(list(metrics))
        task.check()
        dist = sq.distribution()
        task.check()
    finally:
        task._sq = None
        con.close()
    plots = list(plot) if isinstance(plot, (list, tuple)) else ([plot] if plot else [])
    ctx = {"scope": scope, "info": info, "population": pop, "stats": stats, "distribution": dist,
           "plots": plots, "stale": stale, "run_count": run_count, "filters_text": filters_text, "focus": focus,
           "run_counts": run_counts or {}}
    html = R.collection_report_html(ctx)
    task.check()
    resources = {p_["image"]: p_.pop("qimage") for p_ in plots if "qimage" in p_}
    pages = render_pdf(html, path, resources, title=f"Collection analysis report – {R.scope_title(scope, info)}")
    return {"path": path, "pages": pages}


def current_plot_widget(win):
    """The plot on screen (the separate Analysis window when it is active, the workspace when expanded, else the
    embedded panel), or None.  Every view draws the same shared plot state."""
    views = [win.workspace.collection, win.analysis.collection] if win.pages.currentIndex() == 1 else \
        [win.analysis.collection, win.workspace.collection]
    aw = win.analysis_window(create=False) if hasattr(win, "analysis_window") else None
    if aw is not None and aw.isVisible():
        views.insert(0 if _dialog_parent(win) is aw else len(views), aw.panel.collection)
    for v in views:
        p = getattr(v, "plot", None)
        try:
            if p is not None and p.spec is not None:
                return p
        except RuntimeError:
            continue
    return None


def report_plot_candidates(win) -> list[dict]:
    """The charts a Collection report can include (2026-10-28): every chart of a Collection tab that was built for
    the *current* scope and data (a tab's page signature still matches), in tab order - the Plots tab's configured
    plot, the Statistics distribution, the Models charts - each once.  Tabs not built yet are listed as
    unavailable, with the reason."""
    from ...core.analysis import state as S
    from .collection_view import CollectionContent
    from .plot import PlotWidget
    roots = [win.analysis, win.workspace]
    aw = win.analysis_window(create=False) if hasattr(win, "analysis_window") else None
    if aw is not None:
        roots.insert(0, aw)
    seen, out, built_tabs = set(), [], set()
    for root in roots:
        for cc in root.findChildren(CollectionContent):
            for i, tab in enumerate(S.COLL_TABS):
                entry = cc._built.get(i)
                try:
                    current = entry is not None and entry[0] == cc._signature(i)
                except Exception:                                  # noqa: BLE001 - a page being rebuilt
                    current = False
                if not current:
                    continue
                built_tabs.add(tab)
                for pw in cc.pages[i].findChildren(PlotWidget):
                    s = pw.spec
                    if s is None:
                        continue
                    key = (tab, s.kind, s.title or "", getattr(s, "model", None))
                    if key in seen:
                        continue
                    seen.add(key)
                    label = S.COLL_TAB_LABELS[i]
                    out.append({"key": "|".join(str(k) for k in key), "tab": tab, "tab_label": label,
                                "title": s.title or f"{label} chart", "kind": s.kind, "pw": pw, "available": True})
    with_chart = {d["tab"] for d in out}
    for i, tab in enumerate(S.COLL_TABS):
        if tab not in ("plots", "statistics", "models") or tab in with_chart:
            continue
        label = S.COLL_TAB_LABELS[i]
        reason = (f"The {label} tab shows no chart for this collection." if tab in built_tabs
                  else f"Open the {label} tab once to include its charts.")
        out.append({"key": f"{tab}|none", "tab": tab, "tab_label": label, "title": f"{label} charts",
                    "kind": "", "pw": None, "available": False, "reason": reason})
    order = {t: n for n, t in enumerate(S.COLL_TABS)}
    out.sort(key=lambda d: (order.get(d["tab"], 9), not d["available"]))
    return out


def plot_context(win, pw=None, image_name: str = "plot://current", source: str = "") -> dict | None:
    """One chart for the report: image rendered now (GUI thread, light print theme, 2x) + its disclosure."""
    from .widgets import plain_text
    pw = pw if pw is not None else current_plot_widget(win)
    if pw is None or pw.spec is None:
        return None
    s = pw.spec
    img = _light_copy(pw, 960, 600)
    d = s.data
    rep = d.get("representation", "") if isinstance(d, dict) else ""
    # width in the document's CSS pixels (96 per inch, whatever the 300 dpi PDF device): 640 px = 6.7 in of the 7 in A4
    # body.  The former 2000 was wider than the page - Qt clamped the width but kept the height, stretching the chart
    # over a whole page.  At 640 px the chart keeps its aspect ratio and shares its page with its description.
    out = {"image": image_name, "qimage": img, "width": 640, "title": s.title or (f"{source} chart" if source else ""),
           "type": s.kind, "source": source,
           "x": s.x.axis_title() if s.x else "–", "y": s.y.axis_title() if s.y else ("Results" if s.kind != "box" else "–"),
           "colour": plain_text(s.legend_title) if s.legend_title else (s.color if s.color not in ("none", "") else "None"),
           "representation": s.tag, "sampled": rep == SAMPLED,
           "shown": d.get("n_shown", 0) if isinstance(d, dict) else 0,
           "population": d.get("n_valid", 0) if isinstance(d, dict) else 0,
           "n_missing": d.get("n_missing", 0) if isinstance(d, dict) else 0}
    return out


def _light_copy(pw, w: int, h: int) -> QImage:
    """The plot rendered with the light (print) theme - a dark plot must not print as a black block."""
    from ..theme import THEME
    old = THEME.name
    if old != "light":
        THEME.name = "light"           # tokens only; no theme-change signal (nothing else repaints)
    try:
        img = pw.render_image(w, h, 2.0)
    finally:
        THEME.name = old
    return img


# ====================================================================== UI entry points
def _dialog_parent(win):
    """File / print dialogs open over the window the command came from: the separate Analysis window when it
    is the active window (its Options menu), else the main window."""
    from PySide6.QtWidgets import QApplication
    act = QApplication.activeWindow()
    return act if act is not None and act.objectName() == "AnalysisWindow" else win


def export_report(win, kind: str) -> None:
    c = win.analysis_ctl
    st = c.state
    task = getattr(win, "_report_task", None)
    if task is not None and task.running:
        win.notify("info", "A report is already being prepared.")
        return
    if kind == "composition":
        row = c.row if st.active_gone is None else None
        if row is None or not row.result.ok:
            win.notify("info", "Double-click a result to analyse it, then export its report.")
            return
        info = c.run_info(c.record.run_id) if c.record is not None else None
        path, _ = QFileDialog.getSaveFileName(_dialog_parent(win), "Export composition report", R.safe_filename(row.name),
                                              "PDF (*.pdf)")
        if not path:
            return
        args = (_composition_job, row, info, path, _batch_mass(win))
        label = "Preparing the composition report…"
    else:
        sc = st.scope
        if sc is None or st.resolved is None:
            win.notify("info", "Open Collection analysis first.")
            return
        info = c.run_info(sc.run_id)
        # which charts: the user's choice (none is fine - the summary and provenance are always included)
        from .report_dialog import ReportPlotsDialog
        dlg = ReportPlotsDialog(report_plot_candidates(win), _dialog_parent(win))
        ok = dlg.exec()
        chosen = dlg.chosen()
        dlg.deleteLater()
        if not ok:
            return
        name = R.scope_title(sc, info).replace(":", "").replace(",", "").replace(" ", "_").split("_(")[0]
        path, _ = QFileDialog.getSaveFileName(_dialog_parent(win), "Export analysis report", R.safe_filename(name),
                                              "PDF (*.pdf)")
        if not path:
            return
        metrics = list(dict.fromkeys(list(st.stats_metrics) + list(STATS_DEFAULT)))
        stale = None
        if st.stale == "filter":
            stale = "The results-table filter changed after this collection was resolved."
        elif st.newer_results:
            stale = "Newer results were stored after this collection was loaded; refresh it to include them."
        plots = [plot_context(win, d["pw"], f"plot://{n}", f"{d['tab_label']} tab")
                 for n, d in enumerate(chosen)]
        plots = [p_ for p_ in plots if p_ is not None]
        args = (_collection_job, c.repo, sc, info, c.workspace_lo, metrics, plots, stale, c.run_count(sc.run_id),
                filter_text(sc.filters), path, st.stats_focus, {r: c.run_count(r) for r in sc.run_ids})
        label = "Preparing the analysis report…"
    task = ReportTask(win)
    win._report_task = task
    show_progress(win, label, task)
    task.finished.connect(lambda status, value: _report_done(win, status, value))
    task.start(*args)


def show_progress(win, label: str, task: ReportTask) -> None:
    if win.runner.running or win.exporter.running:
        win.notify("info", label)
        return
    win.progress.set_cancellable(True)          # header progress: a report has no other cancel control
    win.progress.set_progress(label.rstrip("…"), 0, 0, None)
    win.progress.cancel.setEnabled(True)
    try:
        win.progress.cancel.clicked.disconnect(win.cancel_calculation)
    except (RuntimeError, TypeError):
        pass
    win.progress.cancel.clicked.connect(task.cancel)
    win.progress.show()
    win._report_progress = True


def _report_done(win, status: str, value) -> None:
    if getattr(win, "_report_progress", False):
        win._report_progress = False
        win.progress.hide()
        try:
            win.progress.cancel.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        win.progress.cancel.clicked.connect(win.cancel_calculation)
    if status == "ok":
        win.notify("success", f"{Path(value['path']).name} ({value['pages']} page"
                              f"{'s' if value['pages'] != 1 else ''}).", title="Report saved")
    elif status == "cancelled":
        win.notify("warning", "No file was written.", title="Report cancelled")
    else:
        win.notify("error", f"The report could not be written: {value}", title="Report failed")


def print_composition(win) -> None:
    """Print the composition report (the former "Print results"): same content as the PDF."""
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter
    c = win.analysis_ctl
    row = c.row if c.state.active_gone is None else None
    if row is None:
        return
    info = c.run_info(c.record.run_id) if c.record is not None else None
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    dlg = QPrintDialog(printer, _dialog_parent(win))
    dlg.setWindowTitle("Print composition report")
    if dlg.exec():
        doc = QTextDocument()
        doc.setDefaultFont(QFont("IBM Plex Sans", 9))
        doc.setHtml(R.composition_report_html(row, info, batch_mass=_batch_mass(win)))
        doc.print_(printer)


def export_analysis_data(win, kind: str) -> None:
    """Statistics CSV, plotted data CSV, plot SVG / PNG of the current collection."""
    c = win.analysis_ctl
    sc = c.state.scope
    if sc is None:
        return
    base = R.safe_filename(f"Run_{sc.run_id}", ext="")
    prov = [f"# HEA Calculator {R.APP_VERSION}, {R.now_text()}",
            f"# Run {sc.run_id}, {sc.population_text()}" + (f", {sc.restriction_text()}" if sc.restricted else "")]
    info = c.run_info(sc.run_id)
    if info is not None:
        prov.append(f"# engine {info.engine_version}, datasets " +
                    "; ".join(f"{k} {v}" for k, v in (info.dataset_ids or {}).items()))
    if kind == "stats_csv":
        stats = c.data.get("stats")
        if not stats:
            win.notify("info", "Open the Statistics tab first.")
            return
        if stats.get("pending"):                       # never export a partial table
            win.notify("info", "Statistics are still being calculated. Export them when the table is complete.")
            return
        path, _ = QFileDialog.getSaveFileName(_dialog_parent(win), "Export statistics", base + "_statistics.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            for line in prov + [f"# N = {stats['n']} results in scope; N/A excluded and counted as missing; "
                                "sample SD (n-1); quartiles Hyndman-Fan type 7; " +
                                ("exact" if stats["exact"] else "approximate (binned)")]:
                fh.write(line + "\n")
            w = csv.writer(fh)
            w.writerow(["Metric", "Unit", "N valid", "N missing", "missing data", "undefined", "not evaluable", "Mean",
                        "SD", "Min", "Q1", "Median", "Q3", "Max"])
            for k, m in stats["metrics"].items():
                dd = DESCRIPTORS.get(k)
                w.writerow([dd.plain if dd else k, dd.unit if dd else "", m["n_valid"], m["n_missing"],
                            m["missing_data"], m["undefined"], m["error"]] +
                           ["" if m[x] is None else repr(m[x]) for x in ("mean", "sd", "min", "q1", "median", "q3", "max")])
        win.notify("success", f"Written to {Path(path).name}.", title="Statistics exported")
        return
    pw = current_plot_widget(win)
    if pw is None or pw.spec is None:
        win.notify("info", "Open the Plots tab first.")
        return
    s = pw.spec
    if kind == "plot_csv":
        path, _ = QFileDialog.getSaveFileName(_dialog_parent(win), "Export plotted data", base + "_plot.csv", "CSV (*.csv)")
        if not path:
            return
        _write_plot_csv(path, s, prov)
        win.notify("success", f"Plotted data exported to {Path(path).name}.")
        return
    ext = "svg" if kind == "plot_svg" else "png"
    path, _ = QFileDialog.getSaveFileName(_dialog_parent(win), "Export plot", f"{base}_plot.{ext}", f"{ext.upper()} (*.{ext})")
    if not path:
        return
    from .widgets import plain_text
    desc = "; ".join(prov) + f"; {s.tag}"
    if ext == "svg":
        pw.export_svg(path, 960, 600, plain_text(s.title), desc)
    else:
        img = pw.render_image(960, 600, 2.0)
        img.setText("Title", plain_text(s.title))
        img.setText("Description", desc)
        img.save(path)
    win.notify("success", f"Plot exported to {Path(path).name}.")


def _write_plot_csv(path: str, s, prov) -> None:
    from .widgets import plain_text
    d = s.data
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        for line in prov + [f"# {plain_text(s.title)}", f"# representation: {s.tag}"]:
            fh.write(line + "\n")
        w = csv.writer(fh)
        if s.kind == "scatter":
            w.writerow(["result_id", "alloy", s.x.plain_title(), s.y.plain_title(), s.color])
            names = d.get("names") or [""] * len(d["ids"])
            for i in range(len(d["ids"])):
                c = d["c"][i] if i < len(d.get("c", [])) else ""
                w.writerow([d["ids"][i], names[i], repr(d["x"][i]), repr(d["y"][i]), "" if c is None else c])
        elif s.kind == "line":
            w.writerow(["result_id", "alloy", s.x.plain_title(), s.y.plain_title()])
            for rid, name, xv, yv in zip(d["ids"], d["names"], d["x"], d["y"][s.y.id]):
                w.writerow([rid, name, repr(xv), "" if yv is None else repr(yv)])
        elif s.kind == "histogram":
            w.writerow(["bin_low", "bin_high", "results"])
            for i, cnt in enumerate(d["counts"]):
                w.writerow([repr(d["edges"][i]), repr(d["edges"][i + 1]), cnt])
        elif s.kind == "binned":
            (x0, x1), (y0, y1) = d["x"], d["y"]
            nx, ny = d["bins"]
            dx, dy = (x1 - x0) / nx, (y1 - y0) / ny
            w.writerow([f"{s.x.plain} low", f"{s.x.plain} high", f"{s.y.plain} low", f"{s.y.plain} high", "results",
                        "value"])
            for bx, by, n, v in d["cells"]:
                w.writerow([repr(x0 + bx * dx), repr(x0 + (bx + 1) * dx), repr(y0 + by * dy), repr(y0 + (by + 1) * dy),
                            n, "" if v is None else (v[0] if isinstance(v, tuple) else repr(v))])
        elif s.kind == "heatmap":
            w.writerow([s.x.plain, s.y.plain, "result_id", "alloy", "value"])
            for (xv, yv), (v, rid, name) in sorted(d["cells"].items()):
                w.writerow([repr(xv), repr(yv), rid, name, v])
        elif s.kind == "box":
            w.writerow(["group", "N", "min", "Q1", "median", "Q3", "max"])
            for g, st in d["groups"].items():
                w.writerow([g, st.get("n_valid")] + [repr(st.get(k)) for k in ("min", "q1", "median", "q3", "max")])
        elif s.kind in ("bars_stacked", "bars_grouped"):
            w.writerow(["row", "class", "results", "denominator"])
            for row in d["rows"]:
                for name, count, _col, _x in row["segments"]:
                    w.writerow([row["label"], name, count, row["denominator"]])


_ = (Qt,)
