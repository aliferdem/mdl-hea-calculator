"""Bibliography of HEA Calculator (no Qt): one source for the About window and Help › Scientific References.

Entries were checked against the publications in ``Model Sources/`` (title pages and running heads).  Fields that
the local sources do not establish are left empty rather than guessed: the title of Guo & Liu (2011) and the full
author list of Guo et al. (2011) are not given.  Formatting follows Materials Science and Engineering: A
(Elsevier numbered style): initials before surnames, sentence-case title, abbreviated journal, volume, (year), pages,
DOI as a URL.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reference:
    key: str
    authors: str
    title: str = ""
    source: str = ""          # journal abbreviation or publisher line
    volume: str = ""
    year: str = ""
    pages: str = ""
    doi: str = ""
    note: str = ""            # what HEA Calculator uses it for
    book: bool = False

    def text(self) -> str:
        """MSE-A style citation without the DOI."""
        parts = [self.authors]
        if self.title:
            parts.append(self.title)
        if self.book:
            return ", ".join(parts + [self.source, self.year]) + "."
        tail = self.source
        if self.volume:
            tail += f" {self.volume}"
        if self.year:
            tail += f" ({self.year})"
        if self.pages:
            tail += f" {self.pages}"
        return ", ".join(parts + [tail]) + "."

    @property
    def url(self) -> str:
        return f"https://doi.org/{self.doi}" if self.doi else ""


MODEL_REFERENCES: tuple[Reference, ...] = (
    Reference("M1", "X. Yang, Y. Zhang",
              "Prediction of high-entropy stabilized solid-solution in multi-component alloys",
              "Mater. Chem. Phys.", "132", "2012", "233–238", "10.1016/j.matchemphys.2011.11.021", "Model M1"),
    Reference("M2", "S. Guo, Q. Hu, C. Ng, C.T. Liu",
              "More than entropy in high-entropy alloys: Forming solid solutions or amorphous phase",
              "Intermetallics", "41", "2013", "96–103", "10.1016/j.intermet.2013.05.002", "Model M2"),
    Reference("M3", "Z. Wang, Y. Huang, Y. Yang, J. Wang, C.T. Liu",
              "Atomic-size effect and solid solubility of multicomponent alloys",
              "Scr. Mater.", "94", "2015", "28–31", "10.1016/j.scriptamat.2014.09.010", "Model M3"),
    Reference("M4", "A.K. Singh, N. Kumar, A. Dwivedi, A. Subramaniam",
              "A geometrical parameter for the formation of disordered solid solutions in multi-component alloys",
              "Intermetallics", "53", "2014", "112–119", "10.1016/j.intermet.2014.04.019", "Model M4"),
    Reference("M5", "Y.F. Ye, Q. Wang, J. Lu, C.T. Liu, Y. Yang",
              "Design of high entropy alloys: A single-parameter thermodynamic rule",
              "Scr. Mater.", "104", "2015", "53–55", "10.1016/j.scriptamat.2015.03.023", "Model M5"),
    Reference("M6", "M.C. Troparevsky, J.R. Morris, P.R.C. Kent, A.R. Lupini, G.M. Stocks",
              "Criteria for predicting the formation of single-phase high-entropy alloys",
              "Phys. Rev. X", "5", "2015", "011041", "10.1103/PhysRevX.5.011041",
              "Model M6; binary formation enthalpies (Supplemental Material, Appendix A)"),
    Reference("M7", "O.N. Senkov, D.B. Miracle",
              "A new thermodynamic parameter to predict formation of solid solution or intermetallic phases in high "
              "entropy alloys", "J. Alloys Compd.", "658", "2016", "603–607", "10.1016/j.jallcom.2015.10.279",
              "Model M7"),
    Reference("M8", "D.J.M. King, S.C. Middleburgh, A.G. McGregor, M.B. Cortie",
              "Predicting the formation and stability of single phase high-entropy alloys",
              "Acta Mater.", "104", "2016", "172–179", "10.1016/j.actamat.2015.11.040", "Model M8"),
)

DATA_REFERENCES: tuple[Reference, ...] = (
    Reference("guo-liu", "S. Guo, C.T. Liu", "", "Prog. Nat. Sci.: Mater. Int.", "21", "2011", "433–446",
              note="Atomic radii (Table 1)"),
    Reference("takeuchi-inoue", "A. Takeuchi, A. Inoue",
              "Classification of bulk metallic glasses by atomic size difference, heat of mixing and period of "
              "constituent elements and its application to characterization of the main alloying element",
              "Mater. Trans.", "46", "2005", "2817–2829", note="Liquid mixing enthalpies"),
    Reference("bakker", "H. Bakker", "Enthalpies in Alloys: Miedema's Semi-Empirical Model",
              "Trans Tech Publications", year="1998", book=True,
              note="Miedema parameters (Tables A1, A2, A5)"),
    Reference("kittel", "C. Kittel", "Introduction to Solid State Physics, 8th ed.",
              "John Wiley & Sons, Hoboken, NJ", year="2004", book=True,
              note="12-coordination radii (Ch. 3, Table 9)"),
    Reference("guo-vec", "S. Guo et al.", "", "J. Appl. Phys.", "109", "2011", "103505",
              note="VEC rule for FCC and BCC phases"),
)

REFERENCES: tuple[Reference, ...] = MODEL_REFERENCES + DATA_REFERENCES

ORIGINAL_SOFTWARE = {
    "name": "HEACalculator",
    "author": "Doğuhan Sarıtürk",
    "repository": "https://github.com/dogusariturk/HEACalculator",
    "doi": "10.5281/zenodo.3590318",
}


def number(key: str) -> int:
    """1-based reference number ([1]-[8] are the models M1-M8)."""
    return next(i for i, r in enumerate(REFERENCES, 1) if r.key == key)


def citation(r: Reference) -> str:
    """The full MSE-A citation with its DOI URL - the one form used everywhere (Analysis, reports, About, Help)."""
    return f"{r.text()} {r.url}".strip()


def model_citation(key: str) -> str:
    """Citation of model ``key`` (M1-M8)."""
    return citation(next(r for r in MODEL_REFERENCES if r.key == key))


def markdown(refs: tuple[Reference, ...] = REFERENCES, start: int = 1) -> str:
    """Numbered Markdown paragraphs ``[n] citation. DOI-link`` (Help › Scientific References)."""
    out = []
    for i, r in enumerate(refs, start):
        line = f"[{i}] {r.text()}"
        if r.url:
            line += f" [{r.url}]({r.url})"
        if r.note and not r.key.startswith("M"):
            line += f" {r.note}."
        out.append(line)
    return "\n\n".join(out) + "\n"
