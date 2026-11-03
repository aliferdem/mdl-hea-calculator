"""Bibliography of HEA Calculator (no Qt): one numbered list for the README, About, Help, Analysis and reports.

[1]-[8] are the models M1-M8, [9]-[13] the data sources listed in the README, and [14] the Miedema source added for
Ca, Sr and Ba (``docs/SCIENTIFIC_DEVELOPMENT_HISTORY.md`` §16).  The README and ``docs/CALCULATION_AUDIT.md`` cite the
same entries as footnotes; titles, author lists, volumes, pages and DOIs were checked against the publications and
their Crossref records.  Books carry no DOI.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reference:
    key: str
    authors: str
    title: str = ""
    source: str = ""          # journal or publisher line
    volume: str = ""
    year: str = ""
    pages: str = ""
    doi: str = ""
    note: str = ""            # what HEA Calculator uses it for
    book: bool = False

    def text(self) -> str:
        """The citation without the DOI."""
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
        """The DOI as a readable URL (the link text)."""
        return f"https://doi.org/{self.doi}" if self.doi else ""

    @property
    def href(self) -> str:
        """The DOI URL as a link target: parentheses percent-encoded so Markdown keeps the whole DOI in the link."""
        return self.url.replace("(", "%28").replace(")", "%29")


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
              "Scripta Materialia", "104", "2015", "53–55", "10.1016/j.scriptamat.2015.03.023", "Model M5"),
    Reference("M6", "M.C. Troparevsky, J.R. Morris, P.R.C. Kent, A.R. Lupini, G.M. Stocks",
              "Criteria for Predicting the Formation of Single-Phase High-Entropy Alloys",
              "Phys. Rev. X", "5", "2015", "011041", "10.1103/PhysRevX.5.011041",
              "Model M6; binary formation enthalpies (Supplemental Material, Appendix A)"),
    Reference("M7", "O.N. Senkov, D.B. Miracle",
              "A new thermodynamic parameter to predict formation of solid solution or intermetallic phases in high "
              "entropy alloys", "J. Alloys Compd.", "658", "2016", "603–607", "10.1016/j.jallcom.2015.10.279",
              "Model M7"),
    Reference("M8", "D.J.M. King, S.C. Middleburgh, A.G. McGregor, M.B. Cortie",
              "Predicting the formation and stability of single phase high-entropy alloys",
              "Acta Materialia", "104", "2016", "172–179", "10.1016/j.actamat.2015.11.040", "Model M8"),
)

DATA_REFERENCES: tuple[Reference, ...] = (
    Reference("guo-liu", "S. Guo, C.T. Liu",
              "Phase stability in high entropy alloys: Formation of solid-solution phase or amorphous phase",
              "Progress in Natural Science: Materials International", "21", "2011", "433–446",
              "10.1016/S1002-0071(12)60080-X",
              note="Atomic radii and Pauling electronegativities (Table 1); electronegativity difference Δχ (Eq. 4)"),
    Reference("takeuchi-inoue", "A. Takeuchi, A. Inoue",
              "Classification of Bulk Metallic Glasses by Atomic Size Difference, Heat of Mixing and Period of "
              "Constituent Elements and Its Application to Characterization of the Main Alloying Element",
              "Materials Transactions", "46", "2005", "2817–2829", "10.2320/matertrans.46.2817",
              note="Liquid mixing enthalpies"),
    Reference("bakker", "H. Bakker", "Enthalpies in Alloys: Miedema’s Semi-empirical Model",
              "Trans Tech Publications, Zürich", year="1998", book=True,
              note="Miedema parameters (Tables A1, A2, A5)"),
    # © 2005 (printed November 2004); the place is Hoboken, NJ, in the publisher's and library records
    Reference("kittel", "C. Kittel", "Introduction to Solid State Physics, 8th ed.",
              "John Wiley & Sons, Hoboken, NJ", year="2005", book=True,
              note="12-coordination radii (Ch. 3, Table 9)"),
    Reference("guo-vec", "S. Guo, C. Ng, J. Lu, C.T. Liu",
              "Effect of valence electron concentration on stability of fcc or bcc phase in high entropy alloys",
              "Journal of Applied Physics", "109", "2011", "103505", "10.1063/1.3587228",
              note="VEC rule for FCC and BCC phases"),
    Reference("de-boer", "F.R. de Boer, R. Boom, W.C.M. Mattens, A.R. Miedema, A.K. Niessen",
              "Cohesion in Metals: Transition Metal Alloys", "North-Holland, Amsterdam", year="1988", book=True,
              note="Miedema pair classification for Ca, Sr and Ba (Eq. 2.33, Fig. 2.28)"),
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
    """The full citation with its DOI URL and the closing period, as plain text (copying, tests)."""
    return f"{r.text()} {r.url}." if r.url else r.text()


def citation_html(r: Reference) -> str:
    """The full citation as Qt rich text: the DOI URL is the link text, the period follows the link."""
    import html
    text = html.escape(r.text(), quote=False)
    if not r.url:
        return text
    return f"{text} <a href=\"{html.escape(r.href)}\">{html.escape(r.url, quote=False)}</a>."


def model_reference(key: str) -> Reference:
    return next(r for r in MODEL_REFERENCES if r.key == key)


def model_citation(key: str) -> str:
    """Citation of model ``key`` (M1-M8), plain text."""
    return citation(model_reference(key))


def markdown(refs: tuple[Reference, ...] = REFERENCES, start: int = 1) -> str:
    """Numbered Markdown paragraphs ``[n] citation. [DOI](DOI).`` (Help › Scientific References)."""
    out = []
    for i, r in enumerate(refs, start):
        line = f"[{i}] {r.text()}"
        if r.url:
            line += f" [{r.url}]({r.href})."
        if r.note and not r.key.startswith("M"):
            line += f" Used for: {r.note[0].lower() + r.note[1:]}."
        out.append(line)
    return "\n\n".join(out) + "\n"


# ---------------------------------------------------------------------- application identity (About)
CONTACT_EMAIL = "erdem.alifethi@gmail.com"
# The public repository of HEA Calculator (the Git remote `origin`; checked public on 2026-11-02).
REPOSITORY_URL: str | None = "https://github.com/aliferdem/mdl-hea-calculator"

# Contributors thanked in the README and About (not software authors; see CITATION.cff for authorship)
ACKNOWLEDGEMENTS = (
    ("Arif Enes Aydın", "https://github.com/ae-aydin", "for his assistance throughout the development of HEA Calculator"),
    ("Taner Göktuğ Tekin", "https://github.com/tekintaner",
     "for the initial implementation of composition import and the evaluation of model performance scores"),
)
