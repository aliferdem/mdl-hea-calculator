# Copyright (c) Ali Fethi Erdem.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.
#
# ui/periodic_table.py

from PySide6.QtWidgets import QPushButton
from PySide6.QtWidgets import QSpacerItem, QSizePolicy

class PeriodicTable:
    def __init__(self, layout, engine, element_colors, callback):
        self.layout = layout
        self.engine = engine
        self.element_colors = element_colors
        self.callback = callback
        self.buttons = {}
        self.add_elements_to_table()

    def add_elements_to_table(self):
        self.layout.setHorizontalSpacing(3)
        self.layout.setVerticalSpacing(3)

        for element, data in self.engine.periodic_table.items():
            row, col, group = data["position"]
            color = self.element_colors.get(group, {"normal": "#333333", "hover": "#444444"})

            button = QPushButton(element)
            button.setCheckable(True)
            button.setFixedSize(32, 32)
            button.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {color["normal"]}; 
                    color: #f4f4f4; 
                    font-size: 11pt;
                    text-align: center;
                    padding: 2px;
                }}
                QPushButton:hover {{
                    background-color: {color["hover"]};
                }}
                QPushButton:checked {{
                    background-color: {color["hover"]};
                }}""")
            
            button.clicked.connect(lambda _, el=element, btn=button: self.callback(el, btn))
            self.layout.addWidget(button, row, col)
            self.buttons[element] = button
        
        spacer = QSpacerItem(40, 200, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.layout.addItem(spacer, 0, 2, 9, 1)