"""Export report (PDF), print, and Analysis data / plot exports - the Qt side.

* :class:`ReportTask` prepares a report on a daemon thread: the repository queries (own read-only
  connection), the HTML (``core/analysis/report.py``) and the PDF (``QTextDocument`` laid out on a
  ``QPdfWriter``: A4, selectable text, header rows repeated on each page, page numbers).  Only the plot image
  is rendered on the GUI thread beforehand (from the plot on screen, so the report shows what was analysed).
  The GUI stays responsive; the task can be cancelled; one finished signal.
* Plot exports (SVG / PNG) render the visible plot through the same painter; data exports stream the
  query answers already on screen with a ``#`` provenance header.
"""

from __future__ import annotations

import csv
import threading
from pathlib import Path

from PySide6.QtCore import QMarginsF, QObject, QSizeF, Qt, QUrl, Signal
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
    "<title> · Page i of n".  Text stays text (selectable, searchable)."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QPainter
    writer = QPdfWriter(path)
    writer.setTitle(title)
    writer.setCreator("HEA Calculator")
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
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), f"{title} · Page {i + 1} of {n}")
    finally:
        p.end()
    return n


class ReportTask(QObject):
    """Latest-wins background report generation; ``finished(status, value)`` (ok/cancelled/error)."""

    finished = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._sq = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, fn, *args) -> None:
        """Run ``fn(task, *args) -> value`` on a daemon thread."""
        self._cancel.clear()

        def work():
            try:
                value = fn(self, *args)
                status = "cancelled" if self._cancel.is_set() else "ok"
            except ReportCancelled:
                status, value = "cancelled", None
            except Exception as exc:                    # noqa: BLE001 - reported to the user
                from ...core.analysis.queries import QueryCancelled
                if isinstance(exc, QueryCancelled):
                    status, value = "cancelled", None
                else:
                    status, value = "error", str(exc)
            try:
                self.finished.emit(status, value)
            except RuntimeError:
                pass
        self._thread = threading.Thread(target=work, name="hea-report", daemon=True)
        self._thread.start()

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


def export_composition_snapshot(parent, row, info) -> None:
    """Export a composition report from a details window (synchronous: one small document)."""
    if row is None or not row.result.ok:
        return
    path, _ = QFileDialog.getSaveFileName(parent, "Export composition report", R.safe_filename(row.name),
                                          "PDF (*.pdf)")
    if not path:
        return
    render_pdf(R.composition_report_html(row, info, batch_mass=_batch_mass(parent)), path,
               title=f"Composition report – {row.name}")


# ====================================================================== collection
def _collection_job(task: ReportTask, repo, scope, info, workspace_lo: int, metrics, plot, stale, run_count,
                    filters_text, path: str, focus: str = "") -> dict:
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
    ctx = {"scope": scope, "info": info, "population": pop, "stats": stats, "distribution": dist,
           "plot": plot, "stale": stale, "run_count": run_count, "filters_text": filters_text, "focus": focus}
    html = R.collection_report_html(ctx)
    task.check()
    resources = {plot["image"]: plot.pop("qimage")} if plot and "qimage" in plot else {}
    pages = render_pdf(html, path, resources, title=f"Collection analysis report – Run {scope.run_id}")
    return {"path": path, "pages": pages}


def current_plot_widget(win):
    """The plot on screen (workspace when expanded, else the embedded panel), or None."""
    views = [win.workspace.collection, win.analysis.collection] if win.pages.currentIndex() == 1 else \
        [win.analysis.collection, win.workspace.collection]
    for v in views:
        p = getattr(v, "plot", None)
        try:
            if p is not None and p.spec is not None:
                return p
        except RuntimeError:
            continue
    return None


def plot_context(win) -> dict | None:
    """The configured plot for the report: image rendered now (GUI thread) + its disclosure."""
    from .widgets import plain_text
    pw = current_plot_widget(win)
    if pw is None or pw.spec is None:
        return None
    s = pw.spec
    img = _light_copy(pw, 960, 600)
    d = s.data
    rep = d.get("representation", "") if isinstance(d, dict) else ""
    out = {"image": "plot://current", "qimage": img, "width": 2000, "title": s.title, "type": s.kind,
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
        path, _ = QFileDialog.getSaveFileName(win, "Export composition report", R.safe_filename(row.name),
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
        path, _ = QFileDialog.getSaveFileName(win, "Export analysis report", R.safe_filename(f"Run_{sc.run_id}"),
                                              "PDF (*.pdf)")
        if not path:
            return
        metrics = list(dict.fromkeys(list(st.stats_metrics) + list(STATS_DEFAULT)))
        stale = None
        if st.stale == "filter":
            stale = "The results-table filter changed after this collection was resolved."
        plot = plot_context(win)
        args = (_collection_job, c.repo, sc, info, c.workspace_lo, metrics, plot, stale, c.run_count(sc.run_id),
                filter_text(sc.filters), path, st.stats_focus)
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
        win.notify("success", f"Report saved: {Path(value['path']).name} ({value['pages']} page"
                              f"{'s' if value['pages'] != 1 else ''}).")
    elif status == "cancelled":
        win.notify("warning", "Report cancelled; no file was written.")
    else:
        win.notify("error", f"The report could not be written: {value}")


def print_composition(win) -> None:
    """Print the composition report (the former "Print results"): same content as the PDF."""
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter
    c = win.analysis_ctl
    row = c.row if c.state.active_gone is None else None
    if row is None:
        return
    info = c.run_info(c.record.run_id) if c.record is not None else None
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    dlg = QPrintDialog(printer, win)
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
    prov = [f"# HEA Calculator {R.APP_VERSION} · {R.now_text()}",
            f"# Run {sc.run_id} · {sc.population_text()}" + (f" · {sc.restriction_text()}" if sc.restricted else "")]
    info = c.run_info(sc.run_id)
    if info is not None:
        prov.append(f"# engine {info.engine_version} · datasets " +
                    "; ".join(f"{k} {v}" for k, v in (info.dataset_ids or {}).items()))
    if kind == "stats_csv":
        stats = c.data.get("stats")
        if not stats:
            win.notify("info", "Open the Statistics tab first.")
            return
        path, _ = QFileDialog.getSaveFileName(win, "Export statistics", base + "_statistics.csv", "CSV (*.csv)")
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
        win.notify("success", f"Statistics exported to {Path(path).name}.")
        return
    pw = current_plot_widget(win)
    if pw is None or pw.spec is None:
        win.notify("info", "Open the Plots tab first.")
        return
    s = pw.spec
    if kind == "plot_csv":
        path, _ = QFileDialog.getSaveFileName(win, "Export plotted data", base + "_plot.csv", "CSV (*.csv)")
        if not path:
            return
        _write_plot_csv(path, s, prov)
        win.notify("success", f"Plotted data exported to {Path(path).name}.")
        return
    ext = "svg" if kind == "plot_svg" else "png"
    path, _ = QFileDialog.getSaveFileName(win, "Export plot", f"{base}_plot.{ext}", f"{ext.upper()} (*.{ext})")
    if not path:
        return
    from .widgets import plain_text
    desc = " · ".join(prov) + f" · {s.tag}"
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
