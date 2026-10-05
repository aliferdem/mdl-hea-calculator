"""Dataset access for the HEA Calculator engine.

All scientific datasets live in ``<app>/data`` as JSON with a ``_metadata`` block that records
provenance.  This module only *reads* them; it never substitutes missing values.  A missing value is
returned as ``None`` so callers can distinguish "no data" from a tabulated physical zero.
"""

from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# Periodic-table categories used for display only.
METALLIC_CATEGORIES = {
    "Alkali metal", "Alkaline earth metal", "Transition metal", "Post-transition metal",
    "Lanthanide", "Actinide", "Metalloid",
}

ELEMENT_NAMES = {
    "H": "Hydrogen", "He": "Helium", "Li": "Lithium", "Be": "Beryllium", "B": "Boron", "C": "Carbon",
    "N": "Nitrogen", "O": "Oxygen", "F": "Fluorine", "Ne": "Neon", "Na": "Sodium", "Mg": "Magnesium",
    "Al": "Aluminium", "Si": "Silicon", "P": "Phosphorus", "S": "Sulfur", "Cl": "Chlorine", "Ar": "Argon",
    "K": "Potassium", "Ca": "Calcium", "Sc": "Scandium", "Ti": "Titanium", "V": "Vanadium",
    "Cr": "Chromium", "Mn": "Manganese", "Fe": "Iron", "Co": "Cobalt", "Ni": "Nickel", "Cu": "Copper",
    "Zn": "Zinc", "Ga": "Gallium", "Ge": "Germanium", "As": "Arsenic", "Se": "Selenium",
    "Br": "Bromine", "Kr": "Krypton", "Rb": "Rubidium", "Sr": "Strontium", "Y": "Yttrium",
    "Zr": "Zirconium", "Nb": "Niobium", "Mo": "Molybdenum", "Tc": "Technetium", "Ru": "Ruthenium",
    "Rh": "Rhodium", "Pd": "Palladium", "Ag": "Silver", "Cd": "Cadmium", "In": "Indium", "Sn": "Tin",
    "Sb": "Antimony", "Te": "Tellurium", "I": "Iodine", "Xe": "Xenon", "Cs": "Caesium", "Ba": "Barium",
    "La": "Lanthanum", "Ce": "Cerium", "Pr": "Praseodymium", "Nd": "Neodymium", "Pm": "Promethium",
    "Sm": "Samarium", "Eu": "Europium", "Gd": "Gadolinium", "Tb": "Terbium", "Dy": "Dysprosium",
    "Ho": "Holmium", "Er": "Erbium", "Tm": "Thulium", "Yb": "Ytterbium", "Lu": "Lutetium",
    "Hf": "Hafnium", "Ta": "Tantalum", "W": "Tungsten", "Re": "Rhenium", "Os": "Osmium",
    "Ir": "Iridium", "Pt": "Platinum", "Au": "Gold", "Hg": "Mercury", "Tl": "Thallium", "Pb": "Lead",
    "Bi": "Bismuth", "Po": "Polonium", "At": "Astatine", "Rn": "Radon", "Fr": "Francium",
    "Ra": "Radium", "Ac": "Actinium", "Th": "Thorium", "Pa": "Protactinium", "U": "Uranium",
    "Np": "Neptunium", "Pu": "Plutonium", "Am": "Americium", "Cm": "Curium", "Bk": "Berkelium",
    "Cf": "Californium", "Es": "Einsteinium", "Fm": "Fermium", "Md": "Mendelevium", "No": "Nobelium",
    "Lr": "Lawrencium", "Rf": "Rutherfordium", "Db": "Dubnium", "Sg": "Seaborgium", "Bh": "Bohrium",
    "Hs": "Hassium", "Mt": "Meitnerium", "Ds": "Darmstadtium", "Rg": "Roentgenium",
    "Cn": "Copernicium", "Nh": "Nihonium", "Fl": "Flerovium", "Mc": "Moscovium",
    "Lv": "Livermorium", "Ts": "Tennessine", "Og": "Oganesson",
}


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


class Datasets:
    """Read-only view of the elemental and binary datasets."""

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        pt = _read_json(self.data_dir / "periodic_table.json")
        self.periodic_table_metadata = pt.pop("_metadata", {})
        self.periodic_table: dict[str, dict] = pt
        mix = _read_json(self.data_dir / "mixing_enthalpy_data.json")
        self.mixing_metadata = mix.pop("_metadata", {})
        self._mixing = mix
        form = _read_json(self.data_dir / "binary_formation_enthalpy_data.json")
        self.formation_metadata = form.pop("_metadata", {})
        self._formation = form
        self._supplementary_radius = set(self.periodic_table_metadata.get("atomic_radius_supplementary", []))

    # ------------------------------------------------------------------ elements
    @cached_property
    def elements(self) -> list[str]:
        """Element symbols ordered by atomic number."""
        return sorted(self.periodic_table, key=lambda el: self.periodic_table[el]["properties"]["atomic_number"])

    def is_element(self, symbol: str) -> bool:
        return symbol in self.periodic_table

    def props(self, element: str) -> dict:
        return self.periodic_table[element]["properties"]

    def prop(self, element: str, key: str):
        """Return a numeric property or ``None`` when it is not tabulated."""
        value = self.periodic_table.get(element, {}).get("properties", {}).get(key)
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def position(self, element: str) -> tuple[int, int, str]:
        row, col, category = self.periodic_table[element]["position"]
        return int(row), int(col), str(category)

    def category(self, element: str) -> str:
        return self.position(element)[2]

    def name(self, element: str) -> str:
        return ELEMENT_NAMES.get(element, element)

    def radius_is_supplementary(self, element: str) -> bool:
        """True when ``atomic_radius`` is not from Guo & Liu (2011) Table 1."""
        return element in self._supplementary_radius

    # ------------------------------------------------------------------ binaries
    @staticmethod
    def _symmetric(table: dict, a: str, b: str):
        row = table.get(a)
        if row is not None and b in row:
            return float(row[b])
        row = table.get(b)
        if row is not None and a in row:
            return float(row[a])
        return None

    def mixing_enthalpy(self, a: str, b: str) -> float | None:
        """Takeuchi & Inoue (2005) liquid mixing enthalpy of the equiatomic A-B pair, kJ/mol."""
        return self._symmetric(self._mixing, a, b)

    def formation_enthalpy(self, a: str, b: str) -> float | None:
        """Troparevsky et al. (2015) binary formation enthalpy, meV/atom."""
        return self._symmetric(self._formation, a, b)

    @cached_property
    def _formation_suspect(self) -> frozenset[str]:
        """Cells the dataset flags as unreliable, derived from ``_metadata.data_quality``.

        A cell is suspect when its magnitude exceeds the publication figure's own colour-scale
        range (``out_of_range_guard_mev``) or when the dataset names it in ``suspect_override``.
        Values are never modified - only labelled.
        """
        dq = self.formation_metadata.get("data_quality", {})
        guard = dq.get("out_of_range_guard_mev")
        out: set[str] = set()
        if guard is not None:
            for a, row in self._formation.items():
                for b, v in row.items():
                    if a != b and abs(float(v)) > float(guard):
                        out.add(f"{a}-{b}")
                        out.add(f"{b}-{a}")
        out.update(dq.get("suspect_override", []))
        return frozenset(out)

    def formation_is_suspect(self, pair: str) -> bool:
        """True when ``pair`` (either orientation, e.g. ``"Fe-Ta"``) is flagged unreliable."""
        return pair in self._formation_suspect

    def formation_suspect_pairs(self) -> frozenset[str]:
        """Every flagged pair, both orientations, as frozen strings."""
        return self._formation_suspect

    @cached_property
    def mixing_elements(self) -> set[str]:
        out = set(self._mixing)
        for row in self._mixing.values():
            out.update(row)
        return out

    @cached_property
    def formation_elements(self) -> set[str]:
        out = set(self._formation)
        for row in self._formation.values():
            out.update(row)
        return out


_DEFAULT: Datasets | None = None


def default_datasets() -> Datasets:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Datasets()
    return _DEFAULT
