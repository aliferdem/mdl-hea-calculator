# Copyright (c) Metals Development Laboratory.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.
#
# Utils/ui_helpers.py

from PySide6.QtWidgets import QLineEdit
from PySide6.QtGui import QDoubleValidator
from PySide6.QtCore import QLocale

def default_line_edit(initial_value: str = "", width: int = 73, height: int = 24) -> QLineEdit:
    """Creates a QLineEdit with validation for double input."""
    line_edit = QLineEdit(initial_value)
    
    validator = QDoubleValidator()
    validator.setNotation(QDoubleValidator.Notation.StandardNotation)
    
    english_locale = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates) # handle decimal points (comma to dot)
    validator.setLocale(english_locale)
    
    line_edit.setValidator(validator)
    line_edit.setFixedSize(int(width), int(height))
    
    return line_edit