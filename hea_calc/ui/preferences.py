"""User preferences persisted in the application's QSettings (one object per main window).

* ``theme`` - the theme *preference*: ``system`` | ``light`` | ``dark`` (the effective theme is resolved
  separately, see ``ui/system_theme.py``; resolving never overwrites the preference);
* ``total_mass`` - the last valid batch mass in grams (Single composition Total mass).  A display / input
  conversion preference only: it changes mass values shown (Single Mass column, Analysis "Mass (… g batch)")
  and never a scientific result;
* ``analysis/composition_tab``, ``analysis/collection_tab``, ``analysis/model`` - the last Analysis tabs
  and the last model shown in Model details.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QObject, QSettings, Signal

THEME_PREFERENCES = ("system", "light", "dark")
DEFAULT_THEME = "system"
DEFAULT_TOTAL_MASS = 2.0


def valid_mass(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def format_mass(g: float) -> str:
    """Grams without needless digits: 2 -> '2', 2.5 -> '2.5', 0.12345 -> '0.1235'."""
    s = f"{g:.4f}".rstrip("0").rstrip(".")
    return s or f"{g:.4g}"


class Preferences(QObject):
    total_mass_changed = Signal(float)
    theme_changed = Signal(str)

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings

    # ------------------------------------------------------------------ theme
    @property
    def theme(self) -> str:
        v = str(self.settings.value("theme", DEFAULT_THEME) or DEFAULT_THEME)
        return v if v in THEME_PREFERENCES else DEFAULT_THEME

    def set_theme(self, pref: str) -> None:
        if pref not in THEME_PREFERENCES:
            raise ValueError(pref)
        if pref != self.theme or not self.settings.contains("theme"):
            self.settings.setValue("theme", pref)
            self.theme_changed.emit(pref)

    # ------------------------------------------------------------------ total mass
    @property
    def total_mass(self) -> float:
        return valid_mass(self.settings.value("total_mass", DEFAULT_TOTAL_MASS)) or DEFAULT_TOTAL_MASS

    def set_total_mass(self, grams) -> bool:
        """Store the last *valid* total mass (positive, finite); invalid values are ignored."""
        g = valid_mass(grams)
        if g is None:
            return False
        if g != self.total_mass or not self.settings.contains("total_mass"):
            self.settings.setValue("total_mass", g)
            self.total_mass_changed.emit(g)
        return True

    # ------------------------------------------------------------------ analysis
    def get(self, key: str, default=None):
        v = self.settings.value(key, default)
        return default if v is None else v

    def put(self, key: str, value) -> None:
        if self.settings.value(key, None) != value:
            self.settings.setValue(key, value)
