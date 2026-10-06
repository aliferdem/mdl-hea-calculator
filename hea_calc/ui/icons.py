"""Centralised icon system: one SVG per icon, recoloured at runtime from theme tokens, cached.

* Monochrome icons use ``currentColor``; ``icon(name, token)`` substitutes the token colour.
* Status icons use role placeholders (``{primary}``, ``{inner}``) mapped to status tokens.
* Stylesheet indicator images (radio/checkbox/chevron) are written once per (icon, colour) to a
  cache directory because QSS can only reference files.
"""

from __future__ import annotations

import hashlib
import tempfile
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme import THEME

ICON_DIR = Path(__file__).with_name("icons")
_CACHE_DIR = Path(tempfile.gettempdir()) / "hea_calculator_icons"

# Additional Carbon icons (32 px grid) defined inline — one definition each.
_INLINE = {
    "close": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M17.4141 16 24 9.4141 22.5859 8 16 14.5859 9.4143 8 8 9.4141 14.5859 16 8 22.5859 9.4143 24 16 17.4141 22.5859 24 24 22.5859 17.4141 16z"/></svg>',
    "copy": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M28,10V28H10V10H28m0-2H10a2,2,0,0,0-2,2V28a2,2,0,0,0,2,2H28a2,2,0,0,0,2-2V10a2,2,0,0,0-2-2Z"/><path d="M4,18H2V4A2,2,0,0,1,4,2H18V4H4Z"/></svg>',
    "download": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M26,24v4H6V24H4v4H4a2,2,0,0,0,2,2H26a2,2,0,0,0,2-2h0V24Z"/><polygon points="26 14 24.59 12.59 17 20.17 17 2 15 2 15 20.17 7.41 12.59 6 14 16 24 26 14"/></svg>',
    "upload": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M6 18 7.41 19.41 15 11.83 15 30 17 30 17 11.83 24.59 19.41 26 18 16 8 6 18z"/><path d="M6 8V4H26V8h2V4a2 2 0 0 0-2-2H6A2 2 0 0 0 4 4V8Z"/></svg>',
    "arrow_up": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><polygon points="16 4 6 14 7.41 15.41 15 7.83 15 28 17 28 17 7.83 24.59 15.41 26 14 16 4"/></svg>',
    "arrow_down": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><polygon points="24.59 16.59 17 24.17 17 4 15 4 15 24.17 7.41 16.59 6 18 16 28 26 18 24.59 16.59"/></svg>',
    "checkmark": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><polygon points="13 24 4 15 5.414 13.586 13 21.171 26.586 7.586 28 9 13 24"/></svg>',
    "reset": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M18,28A12,12,0,1,0,6,16v6.2L2.4,18.6,1,20l6,6,6-6-1.4-1.4L8,22.2V16H8A10,10,0,1,1,18,26Z"/></svg>',
    "printer": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M28,9H25V3H7V9H4a2,2,0,0,0-2,2V21a2,2,0,0,0,2,2H7v6H25V23h3a2,2,0,0,0,2-2V11A2,2,0,0,0,28,9ZM9,5H23V9H9ZM23,27H9V17H23Zm5-6H25V15H7v6H4V11H28Z"/></svg>',
    "search": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M29,27.5859l-7.5521-7.5521a11.0177,11.0177,0,1,0-1.4141,1.4141L27.5859,29ZM4,13a9,9,0,1,1,9,9A9.01,9.01,0,0,1,4,13Z"/></svg>',
    "box": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><rect x="13" y="15" width="6" height="2"/><path d="M26,4H6A2,2,0,0,0,4,6v4a2,2,0,0,0,2,2H7V26a2,2,0,0,0,2,2H23a2,2,0,0,0,2-2V12h1a2,2,0,0,0,2-2V6A2,2,0,0,0,26,4ZM23,26H9V12H23Zm3-16H6V6H26Z"/></svg>',
    "data_table": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M27,3H5A2,2,0,0,0,3,5V27a2,2,0,0,0,2,2H27a2,2,0,0,0,2-2V5A2,2,0,0,0,27,3Zm0,2,0,4H5V5ZM19,17H13V11h6Zm0,2v6H13V19ZM11,17H5V11h6ZM21,11h6v6H21ZM5,19h6v6H5Zm16,6V19h6v6Z"/></svg>',
    "add": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><polygon points="17 15 17 8 15 8 15 15 8 15 8 17 15 17 15 24 17 24 17 17 24 17 24 15 17 15"/></svg>',
}

STATUS_ROLES = {
    "status_ok": {"primary": "status-green"},
    "status_warn": {"primary": "status-yellow", "inner": "status-inner"},
    "status_pair": {"primary": "status-gray"},
    "status_none": {"primary": "status-red"},
}


@lru_cache(maxsize=None)
def _source(name: str) -> str:
    if name in _INLINE:
        return _INLINE[name]
    path = ICON_DIR / f"{name}.svg"
    return path.read_text(encoding="utf-8")


def svg_text(name: str, color: str | None = None) -> str:
    src = _source(name)
    tokens = THEME.tokens
    if name in STATUS_ROLES:
        for role, token in STATUS_ROLES[name].items():
            src = src.replace("{" + role + "}", tokens[token])
        return src
    return src.replace("currentColor", color or tokens["icon-primary"])


_pixmaps: dict[tuple, QPixmap] = {}


def pixmap(name: str, token: str = "icon-primary", size: int = 16, dpr: float = 2.0, color: str | None = None
           ) -> QPixmap:
    col = color or THEME.tokens.get(token, token)
    key = (name, col, size, dpr, THEME.name)
    pm = _pixmaps.get(key)
    if pm is None:
        renderer = QSvgRenderer(QByteArray(svg_text(name, col).encode("utf-8")))
        pm = QPixmap(int(size * dpr), int(size * dpr))
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(p, QRectF(0, 0, size * dpr, size * dpr))
        p.end()
        pm.setDevicePixelRatio(dpr)
        _pixmaps[key] = pm
    return pm


def icon(name: str, token: str = "icon-primary", size: int = 16, disabled_token: str = "icon-disabled") -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, token, size), QIcon.Mode.Normal)
    ic.addPixmap(pixmap(name, disabled_token, size), QIcon.Mode.Disabled)
    return ic


def paint(painter: QPainter, name: str, rect, token: str = "icon-primary", color: str | None = None) -> None:
    renderer = QSvgRenderer(QByteArray(svg_text(name, color or THEME.tokens.get(token, token)).encode("utf-8")))
    renderer.render(painter, QRectF(rect))


_FILE_URLS: dict[tuple[str, str], str] = {}


def file_url(name: str, token: str) -> str:
    """Path usable in QSS ``url(...)`` for the icon in the current theme colour.

    Memoised: a theme switch used to re-hash and re-check every icon file on disk.
    """
    key = (name, token)
    cached = _FILE_URLS.get(key)
    if cached is not None:
        return cached
    color = THEME.tokens.get(token, token)
    data = svg_text(name, color)
    digest = hashlib.sha1(data.encode("utf-8")).hexdigest()[:12]
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _CACHE_DIR / f"{name}_{digest}.svg"
    if not path.exists():
        path.write_text(data, encoding="utf-8")
    _FILE_URLS[key] = path.as_posix()
    return _FILE_URLS[key]


def status_url(name: str) -> str:
    """File URL of a multi-colour status icon in the current theme (for rich-text <img>)."""
    return file_url(name, f"status@{THEME.name}")


def clear_cache() -> None:
    _pixmaps.clear()
    _FILE_URLS.clear()


THEME.changed.connect(lambda _name: clear_cache())


def qsize(n: int) -> QSize:
    return QSize(n, n)
