# Copyright (c) Ali Fethi Erdem.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.
#
# Components/selected_elements_frame.py

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QSpacerItem, QSizePolicy, QPushButton
from Utils.ui_helpers import default_line_edit

class SelectedElementsFrame(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_elements = {}
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(1)

    def add_selected_element(self, element):
        """Adds an element to the selected elements frame."""
        container = QWidget()
        layout = QHBoxLayout(container)

        label = QLabel(element)
        label.setStyleSheet("padding-left: 5px; font-weight: bold;")

        atomic_percent_edit = default_line_edit("0")
        atomic_ratio_edit = default_line_edit("0")
        weight_percent_edit = default_line_edit("0")
        weight_edit = default_line_edit("0")

        layout.addWidget(label)
        layout.addWidget(atomic_ratio_edit)
        layout.addWidget(atomic_percent_edit)
        layout.addWidget(weight_percent_edit)
        layout.addWidget(weight_edit)

        self.selected_elements[element] = {
            "container": container,
            "atomic_percent": atomic_percent_edit,
            "atomic_ratio": atomic_ratio_edit,
            "weight_percent": weight_percent_edit,
            "weight": weight_edit
        }

        self.layout.addWidget(container)

    def remove_selected_element(self, element):
        """Removes an element from the selected elements frame."""
        if element in self.selected_elements:
            self.layout.removeWidget(self.selected_elements[element]["container"])
            self.selected_elements[element]["container"].deleteLater()
            del self.selected_elements[element]

    def clear_elements(self):
        """Clears all selected elements from the frame."""
        for element in list(self.selected_elements.keys()):
            self.remove_selected_element(element)