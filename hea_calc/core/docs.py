"""HEA Calculator documentation model (no Qt): the Help tree, routing, navigation and search.

Content lives in ``hea_calc/docs/pages/<page id>.md`` (Markdown with inline HTML for sub-/superscripts) and
``hea_calc/docs/images/`` (real application screenshots, replaceable independently of the text).  This module
knows nothing about widgets; ``ui/help_window.py`` renders what it returns.

* **Tree** - sections and pages with stable ids (``TREE``); a section is itself a page (its overview).
* **Routing** - ``help://<page>#<anchor>``; legacy ids used by existing links (``models``, ``workload``,
  ``collections`` …) resolve through ``ALIASES``.  Anchors are heading slugs (``slug``).
* **Navigation** - breadcrumb, previous / next in reading order, related topics.
* **Search** - one in-memory index of titles, headings and body text per section, built once; case-insensitive,
  with scientific aliases (delta ↔ δ, mixing enthalpy ↔ ΔHmix, atomic percent ↔ at.% …).
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
PAGES_DIR = DOCS_DIR / "pages"
IMAGES_DIR = DOCS_DIR / "images"
HOME = "home"


@dataclass(frozen=True)
class Node:
    id: str
    title: str
    children: tuple["Node", ...] = ()
    related: tuple[str, ...] = ()


def _n(id_: str, title: str, *children: Node, related: tuple[str, ...] = ()) -> Node:
    return Node(id_, title, tuple(children), related)


# The information architecture (release reconciliation brief, section 46).  Ids are stable link targets.
TREE = _n(HOME, "Documentation Home",
          _n("welcome", "Welcome to HEA Calculator",
             _n("navigating", "Navigating the Documentation", related=("shortcuts", "faq")),
             _n("first-calculation", "Your First Calculation",
                related=("single-composition", "results-table", "composition-analysis"))),
          _n("introduction", "1. Introduction",
             _n("about", "About HEA Calculator", related=("scope", "references")),
             _n("scope", "Scope and Scientific Limitations", related=("model-coverage", "phase-models"))),
          _n("concepts", "2. Key Concepts and Features",
             _n("desktop-layout", "Desktop Layout", related=("navigating", "shortcuts")),
             _n("representations", "Composition Representations",
                related=("single-composition", "composition-space", "symbols")),
             _n("system-size", "System Size and Element Constraints",
                related=("composition-space", "enumeration")),
             _n("model-availability", "Model Support and Availability",
                related=("model-coverage", "result-labels", "elemental-data"))),
          _n("defining", "3. Defining Alloy Compositions",
             _n("single-composition", "Single Composition", related=("representations", "first-calculation")),
             _n("composition-space", "Composition Space", related=("system-size", "enumeration", "workload")),
             _n("composition-expressions", "Composition Expressions",
                related=("expression-syntax", "example-expression")),
             _n("importing", "Importing Compositions", related=("calculation-workflow", "export"))),
          _n("calculations", "4. Performing Calculations",
             _n("calculation-workflow", "Calculation Workflow", related=("workload", "results-table")),
             _n("enumeration", "Composition Enumeration", related=("composition-space", "composition-expressions")),
             _n("workload", "Workload Estimation", related=("enumeration", "calculation-workflow")),
             _n("calculation-settings", "Calculation Settings", related=("phase-models", "symbols"))),
          _n("results", "5. Results and Visualizations",
             _n("results-table", "Results Table", related=("result-labels", "export")),
             _n("composition-analysis", "Individual Composition Analysis",
                related=("result-labels", "phase-models")),
             _n("collection-analysis", "Collection Analysis", related=("plots-statistics", "export")),
             _n("plots-statistics", "Plots and Statistical Analysis", related=("collection-analysis", "symbols")),
             _n("export", "Exporting Results", related=("results-table", "collection-analysis"))),
          _n("examples", "6. Software Examples",
             _n("example-cantor", "Equiatomic CoCrFeMnNi", related=("first-calculation", "composition-analysis")),
             _n("example-space", "Composition Space: Al–Co–Cr–Fe–Ni",
                related=("composition-space", "collection-analysis")),
             _n("example-expression", "Parametric Expression: AlxCoCrFeNi",
                related=("composition-expressions", "plots-statistics"))),
          _n("data-models", "7. Data and Prediction Models",
             _n("elemental-data", "Elemental Property Data", related=("binary-data", "model-coverage")),
             _n("binary-data", "Binary Interaction Data", related=("elemental-data", "model-coverage")),
             _n("model-coverage", "Prediction Model Coverage", related=("phase-models", "model-availability")),
             _n("phase-models", "Phase-Formation Models M1–M8", related=("model-coverage", "references")),
             _n("references", "Scientific References", related=("about", "phase-models"))),
          _n("reference", "8. General Reference",
             _n("symbols", "Symbols, Parameters and Units", related=("result-labels", "phase-models")),
             _n("result-labels", "Prediction Result Labels", related=("model-availability", "results-table")),
             _n("expression-syntax", "Expression Syntax Reference", related=("composition-expressions",)),
             _n("shortcuts", "Keyboard Shortcuts", related=("desktop-layout",)),
             _n("faq", "Frequently Asked Questions", related=("model-availability", "workload"))))

# Existing in-app links and short names -> page ids (help://models#requirements keeps working).
ALIASES = {"models": "model-coverage", "model-support": "model-coverage", "collections": "collection-analysis",
           "workload": "workload", "getting-started": "first-calculation", "expression": "expression-syntax",
           "space": "composition-space", "sweep": "composition-space", "single": "single-composition",
           "statistics": "plots-statistics", "plots": "plots-statistics", "about": "about"}


def _walk(node: Node, parent: str | None = None, out=None):
    out = [] if out is None else out
    out.append((node, parent))
    for c in node.children:
        _walk(c, node.id, out)
    return out


ORDER: list[str] = [n.id for n, _p in _walk(TREE)]             # reading order (depth first)
NODES: dict[str, Node] = {n.id: n for n, _p in _walk(TREE)}
PARENT: dict[str, str | None] = {n.id: p for n, p in _walk(TREE)}


def slug(text: str) -> str:
    """Anchor of a heading: lower case, letters / digits / hyphens (Greek kept)."""
    t = re.sub(r"<[^>]+>", "", text)
    t = unicodedata.normalize("NFKC", t).casefold()
    t = re.sub(r"[^\w\s-]", "", t, flags=re.UNICODE)
    return re.sub(r"[\s_]+", "-", t).strip("-")


@dataclass(frozen=True)
class Route:
    page: str
    anchor: str = ""


def resolve(target: str) -> Route | None:
    """``help://page#anchor``, ``page#anchor`` or a bare id/alias -> a Route to an existing page (None if unknown)."""
    t = (target or "").strip()
    if t.startswith("help://"):
        t = t[len("help://"):]
    t = t.strip("/")
    page, _, anchor = t.partition("#")
    page = page or HOME
    page = ALIASES.get(page, page)
    if page not in NODES:
        return None
    return Route(page, anchor)


def breadcrumb(page: str) -> list[tuple[str, str]]:
    """[(id, title)] from Documentation Home to ``page``."""
    out = []
    p: str | None = page
    while p is not None:
        out.append((p, NODES[p].title))
        p = PARENT.get(p)
    return list(reversed(out))


def neighbours(page: str) -> tuple[str | None, str | None]:
    """(previous, next) in reading order (Home has no previous)."""
    i = ORDER.index(page)
    return (ORDER[i - 1] if i > 0 else None), (ORDER[i + 1] if i + 1 < len(ORDER) else None)


def related(page: str) -> list[str]:
    return [r for r in NODES[page].related if r in NODES]


# ---------------------------------------------------------------------- content
def _descriptor_table() -> str:
    """Markdown table of every descriptor, generated from the engine's descriptor registry (one source of truth for
    names, symbols, units, definitions and equations)."""
    from .analysis.metrics import DESCRIPTORS

    def cell(text: str) -> str:
        return html.unescape(text).replace("|", "\\|").replace("\n", " ")

    rows = ["| Symbol | Quantity | Unit | Definition |", "|---|---|---|---|"]
    for d in DESCRIPTORS.values():
        definition = cell(d.definition)
        if d.equation:
            definition += " " + cell(d.equation) + "."
        rows.append(f"| {cell(d.symbol or d.plain) or '—'} | {cell(d.name)} | {cell(d.unit) or '—'} | {definition} |")
    return "\n".join(rows) + "\n"


def _model_references() -> str:
    from . import references as R
    return R.markdown(R.MODEL_REFERENCES)


def _data_references() -> str:
    from . import references as R
    return R.markdown(R.DATA_REFERENCES, start=len(R.MODEL_REFERENCES) + 1)


GENERATED = {"<!-- descriptors -->": _descriptor_table, "<!-- references:models -->": _model_references,
             "<!-- references:data -->": _data_references}


@lru_cache(maxsize=None)
def source(page: str) -> str:
    """The page's Markdown (generated tables expanded).  A section without its own file gets an overview."""
    path = PAGES_DIR / f"{page}.md"
    if path.exists():
        text = path.read_text(encoding="utf-8")
        for marker, make in GENERATED.items():
            if marker in text:
                text = text.replace(marker, make())
        return text
    node = NODES[page]
    lines = [f"# {node.title}", ""]
    for c in node.children:
        lines.append(f"* [{c.title}](help://{c.id})")
    return "\n".join(lines) + "\n"


def headings(page: str) -> list[tuple[int, str, str]]:
    """[(level, plain text, anchor)] of the page's headings."""
    out = []
    for m in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", source(page), re.M):
        txt = plain(m.group(2))
        out.append((len(m.group(1)), txt, slug(txt)))
    return out


def plain(text: str) -> str:
    """Searchable plain text: no Markdown or HTML markup (sub/superscripts join their base: ΔHmix)."""
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)                    # images
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)                     # links -> label
    t = re.sub(r"</?(sub|sup)>", "", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[*`_>|#]+", " ", t)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------------- search
# Each group lists equivalent spellings; a query term matching one member also finds the others.
SEARCH_ALIASES: tuple[tuple[str, ...], ...] = (
    ("delta", "δ", "size mismatch"),
    ("delta cn12", "δcn12", "dcn12", "delta_cn12", "kittel"),
    ("mixing enthalpy", "δhmix", "dhmix", "enthalpy of mixing"),
    ("mixing entropy", "δsmix", "dsmix", "entropy of mixing"),
    ("atomic percent", "at.%", "at%", "atom percent"),
    ("weight percent", "wt.%", "wt%", "mass percent"),
    ("atomic ratio", "at. ratio", "at ratio"),
    ("omega", "ω"), ("gamma", "γ"), ("lambda", "λ"), ("phi", "φ", "φ (ye)"), ("king", "φ king", "Φ"),
    ("melting temperature", "tm", "melting point"),
    ("valence electron concentration", "vec"),
    ("not available", "n/a", "na"),
    ("solid solution", "ss"), ("intermetallic", "im"), ("multiple phases", "mp"), ("metallic glass", "mg"),
    ("composition space", "sweep", "range"),
    ("expression", "formula", "parametric", "parse", "block"),
    ("range line", "step", "points", "sampling", "variable range"),
    ("formation enthalpy", "δhf", "dhf", "troparevsky"),
    ("density", "ρ", "rho"),
)


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()


def _alias_map() -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for group in SEARCH_ALIASES:
        g = tuple(_fold(x) for x in group)
        for x in g:
            out[x] = tuple(dict.fromkeys(out.get(x, ()) + g))
    return out


@dataclass
class Entry:
    page: str
    anchor: str
    heading: str
    text: str                       # plain text of the section
    hay: str = field(default="")    # folded title + heading + text


@dataclass(frozen=True)
class Hit:
    page: str
    anchor: str
    title: str                      # page title
    section: str                    # parent section title
    heading: str                    # matched heading ("" = page top)
    excerpt: str
    score: float


class SearchIndex:
    """Built once (all pages, split at H2/H3); ``search`` is a pure in-memory scan of a few hundred entries."""

    def __init__(self):
        self.entries: list[Entry] = []
        self.aliases = _alias_map()
        for page in ORDER:
            title = NODES[page].title
            text = source(page)
            parts = re.split(r"^(#{1,3})\s+(.+?)\s*$", text, flags=re.M)
            # parts: [pre, hashes, heading, body, hashes, heading, body, ...]
            pre = plain(parts[0])
            if pre:
                self._add(page, "", "", pre, title)
            for i in range(1, len(parts), 3):
                head = plain(parts[i + 1])
                body = plain(parts[i + 2]) if i + 2 < len(parts) else ""
                level = len(parts[i])
                self._add(page, "" if level == 1 else slug(head), "" if level == 1 else head, body, title,
                          head if level == 1 else "")

    def _add(self, page, anchor, heading, text, title, h1=""):
        e = Entry(page, anchor, heading, text)
        e.hay = _fold(f"{title} \n {h1} \n {heading} \n {text}")
        self.entries.append(e)

    def _alternatives(self, query: str) -> list[tuple[str, ...]]:
        """Query -> AND-list of OR-alternatives (a multi-word alias such as "mixing enthalpy" stays one term)."""
        q = _fold(query).strip()
        terms: list[tuple[str, ...]] = []
        for phrase in sorted(self.aliases, key=len, reverse=True):
            if " " in phrase and phrase in q:
                terms.append(self.aliases[phrase])
                q = q.replace(phrase, " ")
        for w in q.split():
            terms.append(self.aliases.get(w, (w,)))
        return terms

    def search(self, query: str, limit: int = 40) -> list[Hit]:
        terms = self._alternatives(query)
        if not terms:
            return []
        hits: list[Hit] = []
        for e in self.entries:
            score = 0.0
            ok = True
            title = _fold(NODES[e.page].title)
            head = _fold(e.heading)
            for alts in terms:
                best = 0.0
                for a in alts:
                    if a in title:
                        best = max(best, 10.0)
                    elif a and a in head:
                        best = max(best, 6.0)
                    elif a and a in e.hay:
                        best = max(best, 1.0 + min(e.hay.count(a), 5) * 0.2)
                if best == 0:
                    ok = False
                    break
                score += best
            if not ok:
                continue
            parent = PARENT.get(e.page)
            hits.append(Hit(e.page, e.anchor, NODES[e.page].title, NODES[parent].title if parent else "",
                            e.heading, excerpt(e.text, [a for alts in terms for a in alts]), score))
        hits.sort(key=lambda h: (-h.score, ORDER.index(h.page)))
        seen: set[tuple[str, str]] = set()
        out = []
        for h in hits:
            if (h.page, h.anchor) in seen:
                continue
            seen.add((h.page, h.anchor))
            out.append(h)
            if len(out) >= limit:
                break
        return out


def excerpt(text: str, needles: list[str], width: int = 140) -> str:
    folded = _fold(text)
    pos = min((folded.find(n) for n in needles if n and folded.find(n) >= 0), default=0)
    start = max(0, pos - width // 3)
    snippet = text[start:start + width].strip()
    return ("…" if start > 0 else "") + snippet + ("…" if start + width < len(text) else "")


@lru_cache(maxsize=1)
def index() -> SearchIndex:
    return SearchIndex()


# ---------------------------------------------------------------------- rendering (HTML for Qt rich text)
# A deliberately small Markdown subset (no third-party dependency): ATX headings, paragraphs, bullet and numbered
# lists, pipe tables, ``> **Note.**`` callouts, fenced code, images on their own line, **bold**, *italic*,
# `code`, [links](help://page#anchor) and the inline tags <sub> <sup> <br> <kbd>.  The output uses CSS classes;
# the Help window supplies the colours from the theme tokens.
_ALLOWED_TAGS = re.compile(r"</?(sub|sup|br|b|i|em|strong|kbd)\s*/?>", re.I)
_ITEM = re.compile(r"^(\*|-|\d+\.)\s+(.*)$")
_SUPERSCRIPTS = re.compile("[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+")
_SUP_PLAIN = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789−+")


def png_size(path: Path) -> tuple[int, int] | None:
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    except OSError:
        pass
    return None


def inline(text: str) -> str:
    """Inline Markdown -> HTML (escapes everything except the allowed inline tags)."""
    keep: list[str] = []

    def stash(s: str) -> str:
        keep.append(s)
        return f"\x00{len(keep) - 1}\x00"

    t = re.sub(r"`([^`]+)`", lambda m: stash(f"<code>{html.escape(m.group(1))}</code>"), text)
    # Unicode superscripts (mol⁻¹, 10¹⁰) -> <sup>: IBM Plex Sans has no superscript minus
    t = _SUPERSCRIPTS.sub(lambda m: stash("<sup>" + m.group(0).translate(_SUP_PLAIN) + "</sup>"), t)
    t = _ALLOWED_TAGS.sub(lambda m: stash(m.group(0)), t)
    t = html.escape(t, quote=False)
    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
               lambda m: stash(f'<a href="{m.group(2)}">') + m.group(1) + stash("</a>"), t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    return re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], t)


def _cells(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row)]


def to_html(md: str, image_width: int = 640, lead: bool = True) -> str:
    """Markdown subset -> HTML.  Headings carry ``<a name=slug>`` anchors; the first paragraph after the H1 is the
    lead; images are shown at their captured size, scaled down to at most ``image_width`` logical pixels."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    state = {"after_h1": False}
    i = 0

    def flush():
        if para:
            cls = ' class="lead"' if (state["after_h1"] and lead) else ""
            out.append(f"<p{cls}>{inline(' '.join(para))}</p>")
            para.clear()
        state["after_h1"] = False

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            if para:
                flush()
            i += 1
            continue
        if s.startswith("<!--"):
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue
        if s.startswith("```"):
            flush()
            j = i + 1
            code = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                code.append(lines[j])
                j += 1
            out.append(f"<pre>{html.escape(chr(10).join(code))}</pre>")
            i = j + 1
            continue
        m = re.match(r"^(#{1,4})\s+(.+?)\s*$", s)
        if m:
            flush()
            level = len(m.group(1))
            text = m.group(2)
            out.append(f'<h{level}><a name="{slug(plain(text))}"></a>{inline(text)}</h{level}>')
            state["after_h1"] = level == 1
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,})$", s):
            flush()
            out.append("<hr/>")
            i += 1
            continue
        m = re.match(r"^!\[([^\]]*)\]\(([^)\s]+)\)$", s)
        if m:
            flush()
            alt, src = m.group(1), m.group(2)
            size = png_size(DOCS_DIR / src)
            w = min(image_width, size[0]) if size else image_width
            h = f' height="{round(w * size[1] / size[0])}"' if size else ""
            out.append(f'<p class="figure"><img src="{html.escape(src)}" width="{w}"{h}/></p>')
            if alt:
                out.append(f'<p class="caption">{inline(alt)}</p>')
            i += 1
            continue
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{2,}", lines[i + 1].strip()):
            flush()
            head = _cells(s)
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            h = "".join(f'<th align="left">{inline(c)}</th>' for c in head)
            b = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(f'<table class="data" width="100%" cellspacing="0" cellpadding="8"><thead><tr>{h}</tr>'
                       f"</thead>{b}</table>")
            continue
        if s.startswith(">"):
            flush()
            body = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                body.append(lines[i].strip()[1:].strip())
                i += 1
            paras = "\n".join(body).split("\n\n")
            inner = "".join(f"<p>{inline(' '.join(p.split(chr(10))))}</p>" for p in paras if p.strip())
            out.append('<table class="callout" width="100%" cellspacing="0" cellpadding="0"><tr>'
                       f'<td class="bar" width="3"></td><td class="note">{inner}</td></tr></table>')
            continue
        m = _ITEM.match(s)
        if m:
            flush()
            ordered = m.group(1)[0].isdigit()
            items: list[list[str]] = []
            while i < len(lines):
                raw = lines[i]
                ls = raw.strip()
                mm = _ITEM.match(ls)
                if mm and not raw.startswith("  "):
                    items.append([mm.group(2)])
                elif ls and raw.startswith((" ", "\t")) and items:
                    items[-1].append(ls)          # continuation line
                else:
                    break
                i += 1
            out.append(list_html([inline(" ".join(it)) for it in items], ordered))
            continue
        para.append(s)
        i += 1
    flush()
    return "\n".join(out)


def list_html(items: list[str], ordered: bool) -> str:
    """A list as marker / text rows (10.png): Qt's rich-text engine glues its own list markers to the text and
    cannot space them, so the Carbon list anatomy is laid out explicitly - an en dash (unordered) or number
    (ordered) in a 16 / 24 px marker column, the text beside it, 8 px between items."""
    w = 24 if ordered else 16
    rows = "".join(f'<tr><td class="mark" width="{w}" valign="top">{f"{n}." if ordered else "–"}</td>'
                   f'<td class="item" valign="top">{text}</td></tr>' for n, text in enumerate(items, 1))
    return f'<table class="{"ol" if ordered else "ul"}" cellspacing="0" cellpadding="0">{rows}</table>'


def lead_text(page: str) -> str:
    """The page's lead (first paragraph after the H1), for search results and section listings."""
    m = re.search(r"^#\s+[^\n]+\n+(.+?)(?:\n\s*\n|\Z)", source(page), re.S | re.M)
    if not m or m.group(1).lstrip().startswith(("#", "|", "!", ">", "*", "-", "<!--")):
        return ""
    return plain(m.group(1))


def article_markdown(page: str) -> str:
    """The page's Markdown with its generated section listing (``<!-- children -->`` or appended)."""
    text = source(page).rstrip() + "\n"
    node = NODES[page]
    if node.children:
        listing = "".join(f"* [{c.title}](help://{c.id})" + (f" — {lead_text(c.id)}" if lead_text(c.id) else "")
                          + "\n" for c in node.children)
        if "<!-- children -->" in text:
            text = text.replace("<!-- children -->", "\n" + listing)
        else:
            text += "\n## In this section\n\n" + listing
    return text


def article_html(page: str, image_width: int = 640) -> str:
    """The whole article: breadcrumb, H1 + lead + body, related topics and previous / next."""
    crumbs = breadcrumb(page)
    bc = ""
    if len(crumbs) > 1:
        bc = " <span class='sep'>/</span> ".join(
            f'<a href="help://{pid}">{html.escape(title)}</a>' for pid, title in crumbs[:-1])
    body = to_html(article_markdown(page), image_width)
    rel = related(page)
    if rel:
        body += ("\n<h2 class='related'>Related topics</h2>" + list_html(
            [f'<a href="help://{r}">{html.escape(NODES[r].title)}</a>' for r in rel], False))
    prev, nxt = neighbours(page)
    left = (f'<span class="pnlabel">Previous</span><br/><a href="help://{prev}">{html.escape(NODES[prev].title)}</a>'
            if prev else "")
    right = (f'<span class="pnlabel">Next</span><br/><a href="help://{nxt}">{html.escape(NODES[nxt].title)}</a>'
             if nxt else "")
    nav = ('<table class="prevnext" width="100%" cellspacing="0" cellpadding="0"><tr>'
           f'<td class="pn" align="left" width="50%">{left}</td><td class="pn" align="right" width="50%">{right}</td>'
           "</tr></table>")
    head = f'<p class="breadcrumb">{bc}</p>' if bc else ""
    return head + body + nav


def search_html(query: str, hits: list[Hit]) -> str:
    q = html.escape(query.strip())
    if not hits:
        return (f"<h1>Search results</h1><p class='lead'>No topics match “{q}”.</p>"
                "<p>Check the spelling, or try a shorter or more general term: a symbol such as <i>δ</i>, a quantity "
                "such as <i>mixing enthalpy</i>, or a control name such as <i>Range basis</i>.</p>")
    items = []
    for h in hits:
        target = f"help://{h.page}" + (f"#{h.anchor}" if h.anchor else "")
        title = html.escape(h.title) + (f" › {html.escape(h.heading)}" if h.heading else "")
        items.append(f'<p class="hit"><a href="{target}">{title}</a><br/>'
                     f'<span class="hitpath">{html.escape(h.section)}</span><br/>'
                     f'<span class="excerpt">{html.escape(h.excerpt)}</span></p>')
    n = len(hits)
    return f"<h1>Search results</h1><p class='lead'>{n} result{'s' if n != 1 else ''} for “{q}”</p>" + "".join(items)
