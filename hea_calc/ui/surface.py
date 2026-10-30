"""Contextual Carbon layering for components reused on different host surfaces (2026-10-28).

Analysis is shown in five hosts - the compact and the wide docked layouts (the main window's Analysis slot, a
``layer-01`` panel), the dedicated in-window expanded workspace (``background``) and the compact and wide floating
window (``shell``).  Carbon colours a component by the layer it sits on, so the same component needs different
tokens in different hosts.  This module is the one place that decides it:

* a *host* declares the Carbon level of its own surface - the ``carbon_layer`` property (0 = background, 1 =
  layer-01); the floating window's level follows the theme (its shell equals ``layer-01`` in the light theme);
* a *region* (``#AnaRegion`` / ``#AnaRail``) is one level above whatever it sits on;
* :func:`surface_level` walks up from a widget: the regions it is inside plus its host's level;
* :func:`ctx` returns a token's colour for that level.  The application's components were designed (Figma) for a
  layer-01 surface - the compact panel, a region of the expanded workspace - so the layer-relative tokens move one
  level up only on a layer-02 surface (a region of the wide docked layout, a region of the light floating window).

Region backgrounds follow the same rule in the stylesheet (``analysis/widgets.stylesheet_rules``)."""

from __future__ import annotations

from .theme import t

LEVEL_PROP = "carbon_layer"
REGION_NAMES = ("AnaRegion", "AnaRail")

# token designed for a layer-01 surface -> the same role on a layer-02 surface
SHIFT_UP = {
    "layer-01": "layer-02", "layer-hover-01": "layer-hover-02", "layer-selected-01": "layer-selected-02",
    "layer-active-01": "layer-active-02", "border-subtle-01": "border-subtle-02",
    "row-hover": "layer-hover-02", "row-selected": "layer-selected-02", "header-row": "layer-accent-02",
    "row-border": "border-subtle-03",
}


def window_level() -> int:
    """The floating Analysis window's surface (``shell``): level 1 where it equals ``layer-01`` (light), else 0."""
    return 1 if t("shell").lower() == t("layer-01").lower() else 0


def host_level(w) -> int | None:
    v = w.property(LEVEL_PROP)
    if v is not None:
        return int(v)
    if w.objectName() == "AnalysisWindow":
        return window_level()
    return None


def surface_level(widget) -> int:
    """Carbon level of the surface ``widget`` is painted on (its host's level plus the regions it is inside);
    1 when no host is found (the compact panel's design surface)."""
    raises = 0
    w = widget.parentWidget() if widget is not None else None
    while w is not None:
        if w.objectName() in REGION_NAMES:
            raises += 1
        lv = host_level(w)
        if lv is not None:
            return lv + raises
        w = w.parentWidget()
    return 1 + raises


def ctx(widget, token: str) -> str:
    """``token``'s colour for the surface ``widget`` sits on (see the module docstring)."""
    if surface_level(widget) >= 2:
        token = SHIFT_UP.get(token, token)
    return t(token)
