# Copyright (c) Ali Fethi Erdem.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.
#
# Components/periodic_table.py

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QPushButton, QSpacerItem, QSizePolicy

class PeriodicTable(QObject):
    def __init__(self, layout, engine, element_colors, callback, status_label, settings):

        super().__init__()

        self.layout = layout
        self.engine = engine
        self.element_colors = element_colors
        self.callback = callback
        self.status_label = status_label
        self.settings = settings

        self.buttons = {}
        self.add_elements_to_table()

    def add_elements_to_table(self):
        self.layout.setHorizontalSpacing(3)
        self.layout.setVerticalSpacing(3)
        current_theme = self.settings.get_theme()
        for element, data in self.engine.periodic_table.items():
            row, col, group = data["position"]
            color = self.element_colors.get(group, {"normal": "#333333", "hover": "#444444"})
            button = QPushButton(element)
            button.setCheckable(True)
            button.setFixedSize(29, 29)

            if current_theme == "dark":
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
            elif current_theme == "light":
                button.setStyleSheet(
                    f"""
                    QPushButton {{
                        background-color: {color["normal"]}; 
                        color: {color["normal_font"]}; 
                        border-radius: 0px;
                        font-size: 11pt;
                        text-align: center;
                        padding: 2px;
                    }}
                    QPushButton:hover {{
                        background-color: {color["hover"]};
                        color: {color["hover_font"]};
                    }}
                    QPushButton:checked {{
                        background-color: #ffffff;
                        border: 3px solid {color["hover"]};
                        color: {color["hover"]};
                    }}""")

            button.installEventFilter(self)
            button.clicked.connect(lambda _, el=element, btn=button: self.callback(el, btn))
            self.layout.addWidget(button, row, col)
            self.buttons[element] = button

        spacer = QSpacerItem(40, 200, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.layout.addItem(spacer, 0, 2, 9, 1)

    def eventFilter(self, obj, event):
        if isinstance(obj, QPushButton):
            if event.type() == event.Type.Enter:
                element = obj.text()
                group = self.engine.periodic_table[element]["position"][2]
                color = self.element_colors.get(group, {"normal": "#333333", "hover": "#444444"})
                properties = self.engine.periodic_table[element]["properties"]
                position = self.engine.periodic_table[element]["position"]

                melting_point = properties.get("melting_point", "N/A")
                density = properties.get("density", "N/A")
                atomic_weight = properties.get("atomic_weight", "N/A")
                atomic_radius = properties.get("atomic_radius", "N/A")
                nvalence = properties.get("nvalence", "N/A")

                properties_text = (
                    f"<b>{properties['atomic_number']}</b> {position[2]} | "
                    f"<b>Tₘ =</b> {melting_point} K | "
                    f"<b>ρ =</b> {density} g/cm³ | "
                    f"<b>At. Mass =</b> {atomic_weight} u | "
                    f"<b>At. Radius =</b> {atomic_radius} pm | "
                    f"<b>VEC =</b> {nvalence}"
                )
                self.status_label.show()
                self.status_label.setText(properties_text)
                self.status_label.setStyleSheet(
                    f"""
                    QLabel {{
                        background-color: none; 
                        border-radius: 0px;
                        font-size: 10pt;
                        padding: 2px;
                    }}"""
                )
        return super().eventFilter(obj, event)