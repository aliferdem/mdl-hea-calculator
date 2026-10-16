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
    "chevron_right": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><polygon points="22 16 12 26 10.6 24.6 19.2 16 10.6 7.4 12 6 22 16"/></svg>',
    "checkmark": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><polygon points="13 24 4 15 5.414 13.586 13 21.171 26.586 7.586 28 9 13 24"/></svg>',
    "reset": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M18,28A12,12,0,1,0,6,16v6.2L2.4,18.6,1,20l6,6,6-6-1.4-1.4L8,22.2V16H8A10,10,0,1,1,18,26Z"/></svg>',
    "printer": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M28,9H25V3H7V9H4a2,2,0,0,0-2,2V21a2,2,0,0,0,2,2H7v6H25V23h3a2,2,0,0,0,2-2V11A2,2,0,0,0,28,9ZM9,5H23V9H9ZM23,27H9V17H23Zm5-6H25V15H7v6H4V11H28Z"/></svg>',
    "search": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M29,27.5859l-7.5521-7.5521a11.0177,11.0177,0,1,0-1.4141,1.4141L27.5859,29ZM4,13a9,9,0,1,1,9,9A9.01,9.01,0,0,1,4,13Z"/></svg>',
    "box": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><rect x="13" y="15" width="6" height="2"/><path d="M26,4H6A2,2,0,0,0,4,6v4a2,2,0,0,0,2,2H7V26a2,2,0,0,0,2,2H23a2,2,0,0,0,2-2V12h1a2,2,0,0,0,2-2V6A2,2,0,0,0,26,4ZM23,26H9V12H23Zm3-16H6V6H26Z"/></svg>',
    "data_table": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M27,3H5A2,2,0,0,0,3,5V27a2,2,0,0,0,2,2H27a2,2,0,0,0,2-2V5A2,2,0,0,0,27,3Zm0,2,0,4H5V5ZM19,17H13V11h6Zm0,2v6H13V19ZM11,17H5V11h6ZM21,11h6v6H21ZM5,19h6v6H5Zm16,6V19h6v6Z"/></svg>',
    "add": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><polygon points="17 15 17 8 15 8 15 15 8 15 8 17 15 17 15 24 17 24 17 17 24 17 24 15 17 15"/></svg>',
    "maximize": '<svg viewBox="0 0 16 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><polygon points="6,15 6,14 2.7,14 7,9.7 6.3,9 2,13.3 2,10 1,10 1,15"/><polygon points="10,1 10,2 13.3,2 9,6.3 9.7,7 14,2.7 14,6 15,6 15,1"/></svg>',
    "minimize": '<svg viewBox="0 0 16 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><polygon points="2,9 2,10 5.3,10 1,14.3 1.7,15 6,10.7 6,14 7,14 7,9"/><polygon points="14,7 14,6 10.7,6 15,1.7 14.3,1 10,5.3 10,2 9,2 9,7"/></svg>',
    "overflow_menu_vertical": '<svg viewBox="0 0 16 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><circle cx="8" cy="3.5" r="1.2"/><circle cx="8" cy="8" r="1.2"/><circle cx="8" cy="12.5" r="1.2"/></svg>',
    "warning_alt": '<svg viewBox="0 0 16 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M14.5,14h-13c-0.2,0-0.3-0.1-0.4-0.2c-0.1-0.2-0.1-0.3,0-0.5l6.5-12C7.7,1,8,0.9,8.2,1.1c0.1,0,0.2,0.1,0.2,0.2l6.5,12c0.1,0.2,0.1,0.3,0,0.5C14.9,13.9,14.7,14,14.5,14z M2.3,13h11.3L8,2.5L2.3,13z"/><rect x="7.5" y="6" width="1" height="3.5"/><path d="M8,10.8c-0.4,0-0.8,0.3-0.8,0.8s0.3,0.8,0.8,0.8c0.4,0,0.8-0.3,0.8-0.8S8.4,10.8,8,10.8z"/></svg>',
    "warning_filled": '<svg viewBox="0 0 16 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path fill-rule="evenodd" d="M8,1C4.2,1,1,4.2,1,8s3.2,7,7,7s7-3.1,7-7S11.9,1,8,1z M7.5,4h1v5h-1C7.5,9,7.5,4,7.5,4z M8,12.2c-0.4,0-0.8-0.4-0.8-0.8s0.3-0.8,0.8-0.8c0.4,0,0.8,0.4,0.8,0.8S8.4,12.2,8,12.2z"/></svg>',
    "document_export": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><polygon points="13 21 26.17 21 23.59 23.59 25 25 30 20 25 15 23.59 16.41 26.17 19 13 19 13 21"/><path d="M22,14V10a1,1,0,0,0-.29-.71l-7-7A1,1,0,0,0,14,2H4A2,2,0,0,0,2,4V28a2,2,0,0,0,2,2H20a2,2,0,0,0,2-2V26H20v2H4V4h8v6a2,2,0,0,0,2,2h6v2Zm-8-4V4.41L19.59,10Z"/></svg>',
    "zoom_in": '<svg viewBox="0 0 16 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><polygon points="9,6 7,6 7,4 6,4 6,6 4,6 4,7 6,7 6,9 7,9 7,7 9,7"/><path d="M10.7,10C11.5,9,12,7.8,12,6.5C12,3.5,9.5,1,6.5,1S1,3.5,1,6.5S3.5,12,6.5,12c1.3,0,2.5-0.5,3.5-1.3l3.8,3.8l0.7-0.7L10.7,10z M6.5,11C4,11,2,9,2,6.5S4,2,6.5,2S11,4,11,6.5S9,11,6.5,11L6.5,11z"/></svg>',
    "zoom_out": '<svg viewBox="0 0 16 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><rect x="4" y="6" width="5" height="1"/><path d="M10.7,10C11.5,9,12,7.8,12,6.5C12,3.5,9.5,1,6.5,1S1,3.5,1,6.5S3.5,12,6.5,12c1.3,0,2.5-0.5,3.5-1.3l3.8,3.8l0.7-0.7L10.7,10z M6.5,11C4,11,2,9,2,6.5S4,2,6.5,2S11,4,11,6.5S9,11,6.5,11L6.5,11z"/></svg>',
    "fit_to_screen": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><polygon points="22 16 24 16 24 8 16 8 16 10 22 10 22 16"/><polygon points="8 24 16 24 16 22 10 22 10 16 8 16 8 24"/><path d="M26,28H6a2.0023,2.0023,0,0,1-2-2V6A2.0023,2.0023,0,0,1,6,4H26a2.0023,2.0023,0,0,1,2,2V26A2.0023,2.0023,0,0,1,26,28ZM6,6V26H26.0012L26,6Z"/></svg>',
    "chart_scatter": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M30,30H4a2,2,0,0,1-2-2V2H4V28H30Z"/><circle cx="10" cy="22" r="2"/><circle cx="14" cy="15" r="2"/><circle cx="22" cy="15" r="2"/><circle cx="26" cy="6" r="2"/><circle cx="14" cy="8" r="2"/></svg>',
    "chart_histogram": '<svg viewBox="0 0 16 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M2,14V2H1v13h14v-1H2z M4,8h2v5H4V8z M7,4h2v9H7V4z M10,6h2v7h-2V6z"/></svg>',
    "side_panel_close": '<svg viewBox="0 0 16 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M14,2H2C1.4,2,1,2.4,1,3v10c0,0.6,0.4,1,1,1h12c0.6,0,1-0.4,1-1V3C15,2.4,14.6,2,14,2z M2,3h3v10H2V3z M14,13H6V3h8V13z"/></svg>',
    "box_select": '<svg viewBox="0 0 16 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M2,2h3v1H3v2H2V2z M11,2h3v3h-1V3h-2V2z M2,11h1v2h2v1H2V11z M13,11h1v3h-3v-1h2V11z M6,2h4v1H6V2z M6,13h4v1H6V13z M2,6h1v4H2V6z M13,6h1v4h-1V6z"/></svg>',
    "lasso": '<svg viewBox="0 0 16 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M8,2C4.1,2,1,3.8,1,6c0,1.6,1.6,3,4,3.6V11c0,0.6,0.4,1,1,1s1-0.4,1-1v-1.1c0.3,0,0.7,0.1,1,0.1c3.9,0,7-1.8,7-4S11.9,2,8,2z M8,9C4.7,9,2,7.7,2,6s2.7-3,6-3s6,1.3,6,3S11.3,9,8,9z"/></svg>',
    "pan": '<svg viewBox="0 0 16 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><polygon points="8,1 10.5,3.5 9.8,4.2 8.5,2.9 8.5,7.5 13.1,7.5 11.8,6.2 12.5,5.5 15,8 12.5,10.5 11.8,9.8 13.1,8.5 8.5,8.5 8.5,13.1 9.8,11.8 10.5,12.5 8,15 5.5,12.5 6.2,11.8 7.5,13.1 7.5,8.5 2.9,8.5 4.2,9.8 3.5,10.5 1,8 3.5,5.5 4.2,6.2 2.9,7.5 7.5,7.5 7.5,2.9 6.2,4.2 5.5,3.5"/></svg>',
    # Carbon "help", "light", "asleep" (32, @carbon/icons v11.117.0): UI shell header actions
    "help": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M16,2A14,14,0,1,0,30,16,14,14,0,0,0,16,2Zm0,26A12,12,0,1,1,28,16,12,12,0,0,1,16,28Z"/><circle cx="16" cy="23.5" r="1.5"/><path d="M17,8H15.5A4.49,4.49,0,0,0,11,12.5V13h2v-.5A2.5,2.5,0,0,1,15.5,10H17a2.5,2.5,0,0,1,0,5H15v4.5h2V17a4.5,4.5,0,0,0,0-9Z"/></svg>',
    "light": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><rect x="15" y="2" width="2" height="5"/><rect x="21.6675" y="6.8536" width="4.958" height="1.9998" transform="translate(1.5191 19.3744) rotate(-45)"/><rect x="25" y="15" width="5" height="2"/><rect x="23.1466" y="21.6675" width="1.9998" height="4.958" transform="translate(-10.0018 24.1465) rotate(-45)"/><rect x="15" y="25" width="2" height="5"/><rect x="5.3745" y="23.1466" width="4.958" height="1.9998" transform="translate(-14.7739 12.6256) rotate(-45)"/><rect x="2" y="15" width="5" height="2"/><rect x="6.8536" y="5.3745" width="1.9998" height="4.958" transform="translate(-3.253 7.8535) rotate(-45)"/><path d="M16,12a4,4,0,1,1-4,4,4.0045,4.0045,0,0,1,4-4m0-2a6,6,0,1,0,6,6,6,6,0,0,0-6-6Z"/></svg>',
    "asleep": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M13.5025,5.4136A15.0755,15.0755,0,0,0,25.096,23.6082a11.1134,11.1134,0,0,1-7.9749,3.3893c-.1385,0-.2782.0051-.4178,0A11.0944,11.0944,0,0,1,13.5025,5.4136M14.98,3a1.0024,1.0024,0,0,0-.1746.0156A13.0959,13.0959,0,0,0,16.63,28.9973c.1641.006.3282,0,.4909,0a13.0724,13.0724,0,0,0,10.702-5.5556,1.0094,1.0094,0,0,0-.7833-1.5644A13.08,13.08,0,0,1,15.8892,4.38,1.0149,1.0149,0,0,0,14.98,3Z"/></svg>',
    # Carbon "time" (32) and "file--storage" (32, Carbon MCP, @carbon/icons v11.117.0): workload summary
    "time": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M16,30A14,14,0,1,1,30,16,14,14,0,0,1,16,30ZM16,4A12,12,0,1,0,28,16,12,12,0,0,0,16,4Z"/><polygon points="20.59 22 15 16.41 15 7 17 7 17 15.58 22 20.59 20.59 22"/></svg>',
    "file_storage": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M28,20H26v2h2v6H4V22H6V20H4a2.0024,2.0024,0,0,0-2,2v6a2.0024,2.0024,0,0,0,2,2H28a2.0024,2.0024,0,0,0,2-2V22A2.0024,2.0024,0,0,0,28,20Z"/><circle cx="7" cy="25" r="1"/><path d="M22.707,7.293l-5-5A1,1,0,0,0,17,2H11A2.0023,2.0023,0,0,0,9,4V20a2.0023,2.0023,0,0,0,2,2H21a2.0023,2.0023,0,0,0,2-2V8A1,1,0,0,0,22.707,7.293ZM20.5857,8H17V4.4141ZM11,20V4h4V8a2.0023,2.0023,0,0,0,2,2h4V20Z"/></svg>',
    # Carbon notification status icons (16): filled glyph + the inner mark as its own role (Carbon colours the
    # inner path explicitly in notifications, so it stays legible on any surface)
    "notify_warning": '<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path fill="{inner}" d="M7.4 3.9h1.2v5.3H7.4z M8 10.5a0.85 0.85 0 1 0 0.001 0z"/><path fill="{primary}" fill-rule="evenodd" d="M8,1C4.2,1,1,4.2,1,8s3.2,7,7,7s7-3.1,7-7S11.9,1,8,1z M7.5,4h1v5h-1C7.5,9,7.5,4,7.5,4z M8,12.2c-0.4,0-0.8-0.4-0.8-0.8s0.3-0.8,0.8-0.8c0.4,0,0.8,0.4,0.8,0.8S8.4,12.2,8,12.2z"/></svg>',
    "notify_info": '<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path fill="{inner}" d="M7.25 4.75a0.8 0.8 0 1 0 1.5 0a0.8 0.8 0 1 0 -1.5 0z M6 7h2.6v4.1H10v1.1H6v-1.1h1.4V8.1H6z"/><path fill="{primary}" fill-rule="evenodd" d="M8,1a7,7,0,1,0,7,7A7,7,0,0,0,8,1Zm0,3a.8.8,0,1,1-.8.8A.8.8,0,0,1,8,4Zm2,8.1H6V11h1.4V8.1H6.5V7H8.6v4H10Z"/></svg>',
    "notify_error": '<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path fill="{inner}" d="M4.5 5.28L5.28 4.5 11.5 10.72 10.72 11.5z"/><path fill="{primary}" fill-rule="evenodd" d="M8,1C4.1,1,1,4.1,1,8s3.1,7,7,7s7-3.1,7-7S11.9,1,8,1z M10.7,11.5L4.5,5.3l0.8-0.8l6.2,6.2L10.7,11.5z"/></svg>',
    "notify_success": '<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path fill="{inner}" d="M7 10.8L4.5 8.3 5.3 7.5 7 9.2 10.7 5.5 11.5 6.3z"/><path fill="{primary}" fill-rule="evenodd" d="M8,1C4.1,1,1,4.1,1,8s3.1,7,7,7s7-3.1,7-7S11.9,1,8,1z M7,10.8L4.5,8.3l0.8-0.8L7,9.2l3.7-3.7l0.8,0.8L7,10.8z"/></svg>',
    "checkbox_indeterminate": '<svg viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M26,4H6A2,2,0,0,0,4,6V26a2,2,0,0,0,2,2H26a2,2,0,0,0,2-2V6A2,2,0,0,0,26,4ZM22,18H10V14H22Z"/></svg>',
}

STATUS_ROLES = {
    "status_ok": {"primary": "status-green"},
    "status_warn": {"primary": "status-yellow", "inner": "status-inner"},
    "status_pair": {"primary": "status-gray"},
    "status_none": {"primary": "status-red"},
    "status_pending": {"primary": "status-gray"},   # Carbon pending--filled (03_element_empty)
    # Carbon notification icons: $support-* glyph, black inner mark on warning, white elsewhere
    "notify_warning": {"primary": "support-warning", "inner": "status-inner"},
    "notify_info": {"primary": "support-info", "inner": "text-on-color"},
    "notify_error": {"primary": "support-error", "inner": "text-on-color"},
    "notify_success": {"primary": "support-success", "inner": "text-on-color"},
}
# The same icons on an inverse surface (tooltip / toggletip): Carbon's $support-*-inverse / $icon-inverse
# tokens, resolved in the *current* theme - a light application has a dark popup and vice versa.  Never an
# image inversion.
STATUS_ROLES_INVERSE = {
    "status_ok": {"primary": "support-success-inverse"},
    "status_warn": {"primary": "support-warning-inverse", "inner": "status-inner"},
    "status_pair": {"primary": "status-gray-inverse"},
    "status_none": {"primary": "support-error-inverse"},
    "status_pending": {"primary": "status-gray-inverse"},
    "notify_warning": {"primary": "support-warning-inverse", "inner": "status-inner"},
    "notify_info": {"primary": "support-info-inverse", "inner": "text-on-color"},
    "notify_error": {"primary": "support-error-inverse", "inner": "text-on-color"},
    "notify_success": {"primary": "support-success-inverse", "inner": "text-on-color"},
}


@lru_cache(maxsize=None)
def _source(name: str) -> str:
    if name in _INLINE:
        return _INLINE[name]
    path = ICON_DIR / f"{name}.svg"
    return path.read_text(encoding="utf-8")


def svg_text(name: str, color: str | None = None, inverse: bool = False) -> str:
    src = _source(name)
    tokens = THEME.tokens
    if name in STATUS_ROLES:
        for role, token in (STATUS_ROLES_INVERSE if inverse else STATUS_ROLES)[name].items():
            src = src.replace("{" + role + "}", tokens[token])
        return src
    return src.replace("currentColor", color or tokens["icon-inverse" if inverse else "icon-primary"])


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


def paint(painter: QPainter, name: str, rect, token: str = "icon-primary", color: str | None = None,
          inverse: bool = False) -> None:
    """Render the vector icon straight into ``painter`` (crisp at any device pixel ratio).  ``inverse``: the
    icon sits on an inverse surface (tooltip / toggletip) and takes the inverse tokens."""
    col = color or (THEME.tokens.get(token, token) if not inverse or token != "icon-primary"
                    else THEME.tokens["icon-inverse"])
    renderer = QSvgRenderer(QByteArray(svg_text(name, col, inverse).encode("utf-8")))
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
