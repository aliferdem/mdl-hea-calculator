"""Copy the approved Help pages from docs/analysis-redesign into the application package (dev tool).

    .venv/Scripts/python.exe tools/build_help.py

Sources (final copy, never edited here): ``WORKLOAD_HELP_CONTENT.md`` Part B, ``MODEL_SUPPORT_HELP_CONTENT.md``
Part B and ``HELP_UI_CONTENT_LAYOUT.md`` section 4.  Review markers addressed to the design team (UNRESOLVED
labels, "recommended replacement copy") are removed; the CURRENT-behaviour copy they qualify is kept.
Output: ``hea_calc/ui/help/{workload,models,collections}.md`` (shipped with the application).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "analysis-redesign"
OUT = ROOT / "hea_calc" / "ui" / "help"


def section(text: str, start: str, end: str | None) -> str:
    i = text.index(start)
    j = text.index(end, i + len(start)) if end else len(text)
    return text[i:j].strip() + "\n"


def clean(text: str) -> str:
    text = re.sub(r"\*\*Flagged binary data — UNRESOLVED \(CURRENT behaviour described\)\.\*\*", "**Flagged binary data.**",
                  text)
    text = re.sub(r"\n\*Recommended replacement copy after the decision[^\n]*\n(?:[^\n]+\n)*?(?=\n|$)", "\n", text)
    text = re.sub(r" — \*\*UNRESOLVED\*\*[^\n|]*", "", text)
    text = text.replace("(EVID-PARSE-001)", "")
    return text


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    w = (DOCS / "WORKLOAD_HELP_CONTENT.md").read_text(encoding="utf-8")
    (OUT / "workload.md").write_text(clean(section(w, "# Workload estimation", "## Part C")), encoding="utf-8")
    m = (DOCS / "MODEL_SUPPORT_HELP_CONTENT.md").read_text(encoding="utf-8")
    (OUT / "models.md").write_text(clean(section(m, "# Prediction model coverage", "## Part C")), encoding="utf-8")
    h = (DOCS / "HELP_UI_CONTENT_LAYOUT.md").read_text(encoding="utf-8")
    (OUT / "collections.md").write_text(clean(section(h, "# Analysing collections", "## 5. Deep-link anchors")),
                                        encoding="utf-8")
    for p in sorted(OUT.glob("*.md")):
        print(p.relative_to(ROOT), len(p.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
