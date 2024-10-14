# HEA Phase Predictor
# Copyright (C) 2024 Ali Fethi Erdem
# Metals Development Laboratory,
# Middle East Technical University (METU), Ankara, Türkiye
#
# HEA Phase Predictor is a derivative work based on the HEA
# Calculator, originally authored and copyrighted by Doğuhan
# Sarıtürk, and licensed under the GNU General Public
# License, Version 3 (GPLv3). The original HEA Calculator
# remains the intellectual property of Doğuhan Sarıtürk and
# is subject to the terms of the GPLv3.
#
# This program, HEA Phase Predictor, is free software: you can
# redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A
# PARTICULAR PURPOSE. For more details, refer to the GNU
# General Public License.
#
# You should have received a copy of the GNU General Public
# License along with this program. If not, you can find it at:
# https://www.gnu.org/licenses/
#
# The full license text can also be found in the root directory
# of HEA Phase Predictor (HEAPP).
#
# Contact Information:
#
# If you have any questions or concerns about the program or
# its usage, please visit the Authors tab within the About
# HEAPP window for further information.
#
# By using or modifying this software, you agree to the terms
# and conditions outlined in the GNU General Public License.

__author__ = "Ali Fethi Erdem"
__version__ = "0.9"
__email__ = "erdem.alifethi@gmail.com"
__license__ = "GNU General Public License Version 3"
__credits__ = "Original version developed by Doguhan Sariturk under the name of HEA Calculator"

import json
import os
import re
import sys
import pandas as pd
from datetime import datetime
from PySide6.QtCore import (Qt, QTimer)
from PySide6.QtGui import (QIcon, QFont, QAction)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog,
    QGridLayout, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget, QSpacerItem, QSizePolicy,
    QRadioButton, QScrollArea, QProgressBar,
    QDialog, QComboBox, QButtonGroup)

from engine import Engine
from Utils.settings import Settings
from Workers.alloy_calculation import AlloyCalculationWorker
from Workers.composition_generation import CompositionGenerationWorker
from Workers.excel_writer import ExcelWriterWorker
from Utils.io_helpers import read_json
from Utils.ui_helpers import default_line_edit
from Components.periodic_table import PeriodicTable
from Components.about_dialog import AboutDialog

class MDLHEAPP(QMainWindow):
    def __init__(self):
        super().__init__()

        self.settings = Settings()
        self.periodic_table_widget = None

        self.setWindowTitle("MDL | HEA Phase Predictor")
        self.resize(1220, 660)
        self.settings = Settings()

        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

        open_action = QAction("Import an Excel File", self)
        open_action.triggered.connect(self.load_compositions_from_excel)
        file_menu.addAction(open_action)

        self.switch_theme_action = QAction("Dark Theme", self)
        self.switch_theme_action.triggered.connect(self.switch_theme)
        about_action = QAction("About", self)
        about_action.triggered.connect(self.about_dialog)
        menubar.addAction(self.switch_theme_action)
        menubar.addAction(about_action)

        self.composition_worker = None
        self.calculation_worker = None
        self.dialog = None

        self.engine = Engine()

        self.setWindowIcon(QIcon("ui/icons/MDLHEAPP_logo.ico"))

        self.selected_elements = {}

        self.at_ratio_radio = QRadioButton("At. ratio")
        self.at_ratio_radio.setStyleSheet("font-weight: normal; padding-left: 19px;")
        self.at_ratio_radio.setFixedSize(105, 40)

        self.at_percent_radio = QRadioButton("at%")
        self.at_percent_radio.setStyleSheet("font-weight: normal; padding-left: 33px;")
        self.at_percent_radio.setChecked(True)
        self.at_percent_radio.setFixedSize(105, 40)

        self.wt_percent_radio = QRadioButton("wt%")
        self.wt_percent_radio.setStyleSheet("font-weight: normal; padding-left: 32px;")
        self.wt_percent_radio.setFixedSize(105, 40)

        self.weight_radio = QRadioButton("Mass")
        self.weight_radio.setStyleSheet("font-weight: normal; padding-left: 30px;")
        self.weight_radio.setFixedSize(120, 40)

        self.total_label = QLabel("Total:")
        self.total_label.setStyleSheet("font-weight: bold;")
        self.total_atomic_label = QLabel("")
        self.total_weight_percent_label = QLabel("")
        self.total_weight_edit = default_line_edit("0")
        self.step_size_edit = default_line_edit("5")
        self.step_size_edit.setPlaceholderText("step size")
        self.step_size_edit.setFixedWidth(66)
        self.from_at_edit = default_line_edit("")
        self.from_at_edit.setPlaceholderText("initial values")
        self.from_at_edit.textChanged.connect(self.update_all_atomic_percent)
        self.from_at_edit.setFixedWidth(90)
        self.to_at_edit = default_line_edit("")
        self.to_at_edit.setPlaceholderText("last values")
        self.to_at_edit.textChanged.connect(self.update_all_atomic_end)
        self.to_at_edit.setFixedWidth(90)

        self.restriction_values = {}

        self.initUI()

    def _to_subscript(num_str):
        subscript_map = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
        return num_str.translate(subscript_map)

    def initUI(self):
        current_theme = self.settings.get_theme()

        parent_layout = QVBoxLayout()
        parent_widget = QWidget()
        parent_widget.setLayout(parent_layout)

        main_layout = QVBoxLayout()
        main_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        main_layout.setSpacing(30)

        top_container = QHBoxLayout()
        top_container.setSpacing(0)
        top_container.setContentsMargins(0, 0, 0, 0)

        # PARENT_TOP_LAYOUT [STARTS]
        parent_top_widget = QWidget()
        parent_top_widget.setFixedHeight(427)
        parent_top_widget.setObjectName("parent_top")
        parent_top_layout = QVBoxLayout(parent_top_widget)
        parent_top_layout.setContentsMargins(0, 0, 0, 0)
        parent_top_layout.setSpacing(0)
        parent_top_widget.setMinimumWidth(1200)
        parent_top_widget.setMaximumWidth(1366)

        # PARENT_TOP_LAYOUT >> TOP_LAYOUT [STARTS]
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(20, 10, 100, 5)
        logo_label = QLabel("<span style='font-weight: normal;'>MDL</span> <b>HEA Phase Predictor</b>")
        logo_label.setStyleSheet("font-size: 12pt;")
        top_layout.addWidget(logo_label)

        self.content_switcher_group = QButtonGroup(self)
        self.single_comp_radio = QRadioButton("Single Composition")
        self.single_comp_radio.setFixedSize(175.5, 32)
        self.single_comp_radio.setObjectName("single_comp_radio")
        self.single_comp_radio.setChecked(True)
        self.comp_range_radio = QRadioButton("Composition Range")
        self.comp_range_radio.setFixedSize(175.5, 32)
        self.comp_range_radio.setObjectName("comp_range_radio")
        self.content_switcher_group.addButton(self.single_comp_radio)
        self.content_switcher_group.addButton(self.comp_range_radio)

        radio_layout = QHBoxLayout()
        radio_layout.setSpacing(0)
        radio_layout.setContentsMargins(0, 0, 0, 0)
        radio_layout.addWidget(self.single_comp_radio, Qt.AlignmentFlag.AlignCenter)
        radio_layout.addWidget(self.comp_range_radio, Qt.AlignmentFlag.AlignCenter)

        top_layout.addStretch(1)
        top_layout.addLayout(radio_layout)
        parent_top_layout.addLayout(top_layout)
        # PARENT_TOP_LAYOUT >> TOP_LAYOUT [ENDS]

        # PARENT_TOP_LAYOUT >> MIDDLE_LAYOUT [STARTS]
        middle_widget = QWidget()
        middle_widget.setObjectName("parent_top_middle")
        middle_layout = QHBoxLayout(middle_widget)
        middle_layout.setContentsMargins(15, 0, 0, 0)
        middle_widget.setFixedHeight(340)

        periodic_table_frame = QHBoxLayout()
        periodic_table_layout = QGridLayout()

        self.element_colors = read_json("ui/styles/element_colors.json")
        self.status_label = QLabel(self)

        self.periodic_table = PeriodicTable(
            layout= periodic_table_layout,
            engine= self.engine,
            element_colors= self.element_colors,
            callback= self.toggle_element,
            status_label= self.status_label,
            settings= self.settings
        )

        periodic_table_widget = QWidget()
        periodic_table_widget.setLayout(periodic_table_layout)
        periodic_table_widget.setFixedSize(600, 320)
        periodic_table_frame.addWidget(periodic_table_widget)
        middle_layout.addLayout(periodic_table_frame)

        selected_frame_widget = QWidget()
        selected_frame_layout = QVBoxLayout(selected_frame_widget)
        selected_frame_layout.setSpacing(0)

        first_row = QWidget()
        first_row_layout = QHBoxLayout(first_row)
        first_row_layout.setSpacing(0)
        first_row_layout.setContentsMargins(0, 0, 0, 0)

        element_label = QLabel("Element")
        element_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        element_label.setObjectName("element_label")
        element_label.setFixedSize(65, 40)
        first_row_layout.addWidget(element_label)

        self.at_percent_radio.setChecked(True)
        first_row_layout.addWidget(self.at_ratio_radio)
        first_row_layout.addWidget(self.at_percent_radio)
        first_row_layout.addWidget(self.wt_percent_radio)
        first_row_layout.addWidget(self.weight_radio)

        self.at_percent_radio.toggled.connect(self.toggle_input_mode)
        self.wt_percent_radio.toggled.connect(self.toggle_input_mode)
        self.weight_radio.toggled.connect(self.toggle_input_mode)
        self.single_comp_radio.toggled.connect(self.toggle_input_mode)
        self.comp_range_radio.toggled.connect(self.toggle_input_mode)

        selected_frame_layout.addWidget(first_row)

        self.selected_elements_container = QVBoxLayout()
        self.selected_elements_container.setSpacing(1)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setObjectName("selected_elements_scroll")
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setViewportMargins(0, 0, 15, 0)
        scroll_content = QWidget()
        scroll_content.setLayout(self.selected_elements_container)
        scroll_area.setWidget(scroll_content)
        selected_frame_layout.addWidget(scroll_area)
        scroll_content.setFixedWidth(scroll_area.width() - scroll_area.verticalScrollBar().sizeHint().width())
        scroll_area.resizeEvent = lambda event: scroll_content.setFixedWidth(scroll_area.width() - scroll_area.verticalScrollBar().sizeHint().width())
        self.total_row = QWidget()
        total_row_layout = QHBoxLayout(self.total_row)
        total_row_layout.setContentsMargins(10, 10, 10, 0)

        total_row_layout.addItem((QSpacerItem(4, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
        total_row_layout.addWidget(self.total_label)
        total_row_layout.addItem((QSpacerItem(133, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
        total_row_layout.addWidget(self.total_atomic_label)
        total_row_layout.addItem((QSpacerItem(47, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
        total_row_layout.addWidget(self.total_weight_percent_label)
        total_row_layout.addItem((QSpacerItem(31, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
        total_row_layout.addWidget(self.total_weight_edit)
        total_row_layout.addItem((QSpacerItem(21, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))

        selected_frame_layout.addWidget(self.total_row)

        self.step_size_container = QWidget()
        step_size_layout = QHBoxLayout(self.step_size_container)
        step_size_layout.setSpacing(15)
        step_size_layout.setContentsMargins(10, 10, 0, 0)
        step_size_layout.addItem((QSpacerItem(65, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
        step_size_layout.addStretch(1)
        step_size_layout.addWidget(self.from_at_edit)
        step_size_layout.addWidget(self.step_size_edit)
        step_size_layout.addWidget(self.to_at_edit)
        step_size_layout.addStretch(1)
        
        selected_frame_layout.addWidget(self.step_size_container)
        selected_frame_widget.setFixedSize(518, 326)
        middle_layout.addStretch(1)
        middle_layout.addWidget(selected_frame_widget)

        parent_top_layout.addWidget(middle_widget)
        # PARENT_TOP_LAYOUT >> MIDDLE_LAYOUT [ENDS]

        # PARENT_TOP_LAYOUT >> BOTTOM_LAYOUT [STARTS]
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(10, 0, 0, 0)
        bottom_layout.setSpacing(0)

        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        bottom_layout.addWidget(self.status_label)

        clear_selected_button = QPushButton("Clear")
        clear_selected_button.setProperty("class", "ghost_button")
        clear_selected_button.setFixedSize(76, 40)
        clear_selected_button.clicked.connect(self.clear_selected_elements)

        self.calculate_button = QPushButton("Calculate")
        self.calculate_button.setProperty("class", "primary_button")
        self.calculate_button.setFixedSize(141,40)
        self.calculate_button.clicked.connect(self.on_calculate_button_click)

        self.filter_button = QPushButton("Filter")
        self.filter_button.setProperty("class", "ghost_button")
        self.filter_button.setFixedSize(76, 40)
        self.filter_button.clicked.connect(self.show_restrictions_window)

        selected_button_container = QWidget()
        selected_button_container.setFixedWidth(509)
        selected_button_layout = QHBoxLayout(selected_button_container)
        selected_button_layout.setSpacing(0)
        selected_button_layout.setContentsMargins(0, 0, 0, 0)
        selected_button_layout.addWidget(self.filter_button)
        selected_button_layout.addStretch(1)
        selected_button_layout.addWidget(clear_selected_button)
        selected_button_layout.addWidget(self.calculate_button)

        bottom_layout.addStretch(1)
        bottom_layout.addWidget(selected_button_container)

        parent_top_layout.addLayout(bottom_layout)

        main_scroll_area = QScrollArea()
        main_scroll_area.setWidgetResizable(True)
        main_scroll_area.setObjectName("main_scroll")
        main_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        main_scroll_area.setViewportMargins(0, 0, 15, 0)
        main_widget = QWidget()
        main_widget.setLayout(main_layout)
        main_scroll_area.setWidget(main_widget)
        parent_layout.addWidget(main_scroll_area)

        self.old_pos = None
        
        if current_theme == "dark":
            with open("ui/styles/styleSheet_dark.qss", "r") as f:
                self.dark_stylesheet = f.read()
            self.setStyleSheet(self.dark_stylesheet)
            self.switch_theme_action.setText("Light Theme")
            self.switch_theme_action.setToolTip("Switch to Light Theme")
        elif current_theme == "light":
            with open("ui/styles/styleSheet_light.qss", "r") as f:
                self.light_stylesheet = f.read()
            self.setStyleSheet(self.light_stylesheet)
            self.switch_theme_action.setText("Dark Theme")
            self.switch_theme_action.setToolTip("Switch to Dark Theme")

        top_container.addWidget(parent_top_widget)
        main_layout.addLayout(top_container)

        # PARENT_BOTTOM_LAYOUT [STARTS]
        parent_bottom_layout = QVBoxLayout()
        parent_bottom_layout.setContentsMargins(0, 0, 0, 0)
        parent_bottom_layout.setSpacing(0)

        btop_widget = QWidget()
        btop_layout = QHBoxLayout(btop_widget)
        btop_widget.setObjectName("parent_top")
        btop_layout.setContentsMargins(10, 0, 0, 0)
        btop_layout.setSpacing(0)
        btop_widget.setMinimumWidth(1200)
        btop_widget.setMaximumWidth(1366)
        btop_widget.setFixedHeight(32)

        self.table_label = QLabel("")
        self.table_label.setObjectName("table_label")
        btop_layout.addWidget(self.table_label)
        btop_layout.addStretch()

        bottom_buttons_layout = QHBoxLayout()
        bottom_buttons_layout.setSpacing(0)
        clear_alloy_button = QPushButton("Clear")
        clear_alloy_button.setFixedSize(76,32)
        clear_alloy_button.setProperty("class", "ghost_button")
        clear_alloy_button.clicked.connect(self.clear_alloy_info)
        bottom_buttons_layout.addWidget(clear_alloy_button)
        save_button = QPushButton("Save to Excel")
        save_button.setProperty("class", "secondary_button")
        save_button.setFixedSize(141, 32)
        save_button.clicked.connect(self.save_to_excel)
        bottom_buttons_layout.addWidget(save_button)

        btop_layout.addLayout(bottom_buttons_layout)
        parent_bottom_layout.addWidget(btop_widget)

        self.alloy_table = QTableWidget(0, 16)
        self.alloy_table.verticalHeader().setVisible(False)
        self.alloy_table.setShowGrid(False)
        self.alloy_table.setColumnWidth(0, 140)
        self.alloy_table.setColumnWidth(1, 94)
        self.alloy_table.setColumnWidth(2, 74)
        self.alloy_table.setColumnWidth(3, 74)
        self.alloy_table.setColumnWidth(4, 97)
        self.alloy_table.setColumnWidth(5, 46)
        self.alloy_table.setColumnWidth(6, 96)
        self.alloy_table.setColumnWidth(7, 67)
        self.alloy_table.setColumnWidth(8, 74)
        self.alloy_table.setColumnWidth(9, 99)
        self.alloy_table.setColumnWidth(10, 58)
        self.alloy_table.setColumnWidth(11, 62)
        self.alloy_table.setColumnWidth(12, 60)
        self.alloy_table.setColumnWidth(13, 59)
        self.alloy_table.setColumnWidth(14, 59)
        self.alloy_table.setColumnWidth(15, 120)
        self.alloy_table.setMinimumHeight(336)
        self.alloy_table.setMinimumWidth(1200)
        self.alloy_table.setMaximumWidth(1366)
        self.alloy_table.setHorizontalHeaderLabels(["Alloy", "Density (g/cm³)", "δ", "γ", "ΔHₘᵢₓ (kJ/mol)", "VEC", "ΔSₘᵢₓ (kJ/mol)", "Tₘ (K)", 
                                                    "Ω", "Crystal Str.", "Model 1", "Model 2", "Model 3", "Model 4", "Model 5", "Model 6"])

        self.alloy_table.cellClicked.connect(self.update_label)
        parent_bottom_layout.addWidget(self.alloy_table)
        main_layout.addLayout(parent_bottom_layout)

        self.setCentralWidget(parent_widget)
        self.toggle_input_mode()

    def about_dialog(self):
        dialog = AboutDialog(self)
        dialog.exec()

    def switch_theme(self):
        current_theme = self.settings.get_theme()
        new_theme = "light" if current_theme == "dark" else "dark"
        self.settings.set_theme(new_theme)
        if new_theme == "dark":
            for element, button in self.periodic_table.buttons.items():
                group = self.engine.periodic_table[element]["position"][2]
                color = self.element_colors.get(group, {"normal": "#333333", "hover": "#444444"})
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
            with open("ui/styles/styleSheet_dark.qss", "r") as f:
                self.dark_stylesheet = f.read()
            self.setStyleSheet(self.dark_stylesheet)
            self.switch_theme_action.setText("Light Theme")
            self.switch_theme_action.setToolTip("Switch to Light Theme")
        elif new_theme == "light":
            for element, button in self.periodic_table.buttons.items():
                group = self.engine.periodic_table[element]["position"][2]
                color = self.element_colors.get(group, {"normal": "#333333", "hover": "#444444"})
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
            with open("ui/styles/styleSheet_light.qss", "r") as f:
                self.dark_stylesheet = f.read()
            self.setStyleSheet(self.dark_stylesheet)
            self.switch_theme_action.setText("Dark Theme")
            self.switch_theme_action.setToolTip("Switch to Dark Theme")

    def update_label(self, row, column):
        item = self.alloy_table.item(row, column)
        if item:
            self.table_label.setText(f"{item.text()}")
        else:
            self.table_label.setText("N/A")

    def add_selected_element_to_frame(self, element):
        container = QWidget()
        layout = QHBoxLayout()
        container.setLayout(layout)

        label = QLabel(element)
        label.setStyleSheet("padding-left: 5px; font-weight: bold;")

        atomic_percent_edit = default_line_edit("0")
        atomic_ratio_edit = default_line_edit("0")
        weight_percent_edit = default_line_edit("0")
        weight_edit = default_line_edit("0")
        to_label = QLabel("to")
        to_label.setFixedWidth(30)
        to_label.setStyleSheet("color: rgba(255, 255, 255, 0);")
        transparent_widget = QPushButton()
        transparent_widget.setFixedSize(39, 24)
        transparent_widget.setEnabled(False)

        self.selected_elements[element] = {
            "atomic_percent": atomic_percent_edit,
            "atomic_ratio": atomic_ratio_edit,
            "weight_percent": weight_percent_edit,
            "weight": weight_edit,
            "tw": transparent_widget,
            "to": to_label
        }

        atomic_percent_edit.textChanged.connect(lambda: self.update_ar_wp_w(element))
        atomic_ratio_edit.textChanged.connect(lambda: self.update_ap_wp_w(element))
        weight_percent_edit.textChanged.connect(lambda: self.update_ap_ar_w(element))
        weight_edit.textChanged.connect(lambda: self.update_ap_ar_wp(element))
        self.total_weight_edit.textChanged.connect(lambda: self.update_weight(element))

        layout.addWidget(label, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(atomic_ratio_edit, Qt.AlignmentFlag.AlignLeft)
        layout.addItem((QSpacerItem(26, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
        layout.addWidget(atomic_percent_edit, Qt.AlignmentFlag.AlignLeft)
        layout.addItem((QSpacerItem(26, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
        layout.addWidget(weight_percent_edit, Qt.AlignmentFlag.AlignLeft)
        layout.addItem((QSpacerItem(26, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
        layout.addWidget(weight_edit, Qt.AlignmentFlag.AlignLeft)
        layout.addItem((QSpacerItem(3, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))

        atomic_percent_end_edit = default_line_edit("35")
        atomic_percent_end_edit.setFixedSize(90, 24)

        layout.addWidget(to_label)
        layout.addWidget(atomic_percent_end_edit)
        layout.addWidget(transparent_widget)
        self.selected_elements[element]["atomic_end"] = atomic_percent_end_edit

        self.selected_elements_container.addWidget(container)
        self.selected_elements_container.setAlignment(Qt.AlignmentFlag.AlignTop)
        total_elements = len(self.selected_elements)
        if total_elements > 0:
            if self.at_percent_radio.isChecked():
                equ_atomic_percent = 100/total_elements
                for edits in self.selected_elements.values():
                    edits["atomic_percent"].blockSignals(True)
                    edits["atomic_percent"].setText(f"{equ_atomic_percent:.2f}")
                    edits["atomic_percent"].blockSignals(False)
            elif self.at_ratio_radio.isChecked():
                for edits in self.selected_elements.values():
                    edits["atomic_ratio"].blockSignals(True)
                    edits["atomic_ratio"].setText("1.00")
                    edits["atomic_ratio"].blockSignals(False)
                    self.update_all_percentages()
        self.update_all_percentages()

        self.toggle_input_mode()

    def update_all_percentages(self):
        if self.at_percent_radio.isChecked():
            max_percent = max((float(edit["atomic_percent"].text() or 0) for edit in self.selected_elements.values()), default=0)
            for element, edits in self.selected_elements.items():
                total_weight = float(self.total_weight_edit.text() or 0)
                atomic_percent = float(edits["atomic_percent"].text() or 0)
                atomic_ratio = (atomic_percent / max_percent) if max_percent != 0 else 0
                edits["atomic_ratio"].blockSignals(True)
                edits["atomic_ratio"].setText(f"{atomic_ratio:.4f}")
                edits["atomic_ratio"].blockSignals(False)
                weight_percent = self.atomic_to_weight_percent(element, atomic_percent)
                edits["weight_percent"].blockSignals(True)
                edits["weight_percent"].setText(f"{weight_percent:.4f}")
                edits["weight_percent"].blockSignals(False)
                weight = total_weight * (weight_percent / 100)
                edits["weight"].blockSignals(True)
                edits["weight"].setText(f"{weight:.5f}")
                edits["weight"].blockSignals(False)
        elif self.at_ratio_radio.isChecked():
            total_atomic_ratio = sum(float(edit["atomic_ratio"].text() or 0) for edit in self.selected_elements.values())
            for element, edits in self.selected_elements.items():
                total_weight = float(self.total_weight_edit.text() or 0)
                atomic_ratio = float(edits["atomic_ratio"].text() or 0)
                atomic_percent = (atomic_ratio / total_atomic_ratio * 100) if total_atomic_ratio != 0 else 0
                weight_percent = self.atomic_to_weight_percent(element, atomic_percent)
                weight = total_weight * (weight_percent / 100)
                edits["atomic_percent"].blockSignals(True)
                edits["atomic_percent"].setText(f"{atomic_percent:.4f}")
                edits["atomic_percent"].blockSignals(False)
                edits["weight_percent"].blockSignals(True)
                edits["weight_percent"].setText(f"{weight_percent:.4f}")
                edits["weight_percent"].blockSignals(False)
                edits["weight"].blockSignals(True)
                edits["weight"].setText(f"{weight:.5f}")
                edits["weight"].blockSignals(False)
        elif self.wt_percent_radio.isChecked():
            max_percent = max((float(edit["atomic_percent"].text() or 0) for edit in self.selected_elements.values()), default=0)
            for element, edits in self.selected_elements.items():
                total_weight = float(self.total_weight_edit.text() or 0)
                weight_percent = float(edits["weight_percent"].text() or 0)
                atomic_percent = self.weight_to_atomic_percent(element, weight_percent)
                atomic_ratio = (atomic_percent / max_percent) if max_percent != 0 else 0
                edits["atomic_ratio"].blockSignals(True)
                edits["atomic_ratio"].setText(f"{atomic_ratio:.4f}")
                edits["atomic_ratio"].blockSignals(False)
                edits["atomic_percent"].blockSignals(True)
                edits["atomic_percent"].setText(f"{atomic_percent:.4f}")
                edits["atomic_percent"].blockSignals(False)
                weight = total_weight * (weight_percent / 100)
                edits["weight"].blockSignals(True)
                edits["weight"].setText(f"{weight:.5f}")
                edits["weight"].blockSignals(False)
        elif self.weight_radio.isChecked():
            max_percent = max((float(edit["atomic_percent"].text() or 0) for edit in self.selected_elements.values()), default=0)
            total_weight = sum(float(edit["weight"].text() or 0) for edit in self.selected_elements.values())
            for element, edits in self.selected_elements.items():
                weight = float(edits["weight"].text() or 0)
                weight_percent = (weight / total_weight * 100) if total_weight != 0 else 0
                atomic_percent = self.weight_to_atomic_percent(element, weight_percent)
                atomic_ratio = (atomic_percent / max_percent) if max_percent != 0 else 0
                edits["atomic_ratio"].blockSignals(True)
                edits["atomic_ratio"].setText(f"{atomic_ratio:.4f}")
                edits["atomic_ratio"].blockSignals(False)
                self.total_weight_edit.blockSignals(True)
                self.total_weight_edit.setText(f"{total_weight:.5f}")
                self.total_weight_edit.blockSignals(False)
                edits["weight_percent"].blockSignals(True)
                edits["weight_percent"].setText(f"{weight_percent:.4f}")
                edits["weight_percent"].blockSignals(False)
                edits["atomic_percent"].blockSignals(True)
                edits["atomic_percent"].setText(f"{atomic_percent:.4f}")
                edits["atomic_percent"].blockSignals(False)

        max_percent = max((float(edit["atomic_percent"].text() or 0) for edit in self.selected_elements.values()), default=0)
        total_weight = sum(float(edit["weight"].text() or 0) for edit in self.selected_elements.values())
        total_atomic_ratio = sum(float(edit["atomic_ratio"].text() or 0) for edit in self.selected_elements.values())

        total_atomic_percent = sum(float(edit["atomic_percent"].text() or 0) for edit in self.selected_elements.values())
        total_weight_percent = sum(float(edit["weight_percent"].text() or 0) for edit in self.selected_elements.values())

        self.total_atomic_label.setText(f"{total_atomic_percent:.0f}%")
        self.total_weight_percent_label.setText(f"{total_weight_percent:.0f}%")

    def update_ar_wp_w(self, element): # Updates At. Ratio, Wt. %, Weight (g)
        self.update_all_percentages()
        if not self.at_percent_radio.isChecked():
            return  # Do not update if At. % mode is not selected
        try:
            atomic_percent = float(self.selected_elements[element]["atomic_percent"].text() or 0)
            weight_percent = self.atomic_to_weight_percent(element, atomic_percent)
            total_weight = float(self.total_weight_edit.text() or 0)
            max_percent = max((float(edit["atomic_percent"].text() or 0) for edit in self.selected_elements.values()), default=0)
            atomic_ratio = (atomic_percent / max_percent) if max_percent != 0 else 0
            self.selected_elements[element]["atomic_ratio"].blockSignals(True)
            self.selected_elements[element]["atomic_ratio"].setText(f"{atomic_ratio:.4f}")
            self.selected_elements[element]["atomic_ratio"].blockSignals(False)
            self.selected_elements[element]["weight_percent"].blockSignals(True)
            self.selected_elements[element]["weight_percent"].setText(f"{weight_percent:.4f}")
            self.selected_elements[element]["weight_percent"].blockSignals(False)
            weight = total_weight * (weight_percent / 100)
            self.selected_elements[element]["weight"].blockSignals(True)
            self.selected_elements[element]["weight"].setText(f"{weight:.5f}")
            self.selected_elements[element]["weight"].blockSignals(False)
        except ValueError:
            return 0
        self.update_all_percentages()

    def update_ap_wp_w(self, element): # Updates At. %, Wt. %, Weight (g)
        self.update_all_percentages()
        if not self.at_ratio_radio.isChecked():
            return
        try:
            atomic_ratio = float(self.selected_elements[element]["atomic_ratio"].text() or 0)
            total_atomic_ratio = sum(float(self.selected_elements[el]["atomic_ratio"].text() or 0) for el in self.selected_elements)
            total_weight = float(self.total_weight_edit.text() or 0)
            atomic_percent = (atomic_ratio / total_atomic_ratio * 100) if total_atomic_ratio != 0 else 0
            self.selected_elements[element]["atomic_percent"].blockSignals(True)
            self.selected_elements[element]["atomic_percent"].setText(f"{atomic_percent:.4f}")
            self.selected_elements[element]["atomic_percent"].blockSignals(False)
            weight_percent = self.atomic_to_weight_percent(element, atomic_percent)
            self.selected_elements[element]["weight_percent"].blockSignals(True)
            self.selected_elements[element]["weight_percent"].setText(f"{weight_percent:.4f}")
            self.selected_elements[element]["weight_percent"].blockSignals(False)
            weight = total_weight * (weight_percent / 100)
            self.selected_elements[element]["weight"].blockSignals(True)
            self.selected_elements[element]["weight"].setText(f"{weight:.5f}")
            self.selected_elements[element]["weight"].blockSignals(False)
        except ValueError:
            return 0
        self.update_all_percentages()

    def update_ap_ar_w(self, element):
        self.update_all_percentages()
        if not self.wt_percent_radio.isChecked():
            return  # Do not update if Wt. % mode is not selected
        try:
            weight_percent = float(self.selected_elements[element]["weight_percent"].text() or 0)
            atomic_percent = self.weight_to_atomic_percent(element, weight_percent)
            total_weight = float(self.total_weight_edit.text() or 0)
            max_percent = max((float(edit["atomic_percent"].text() or 0) for edit in self.selected_elements.values()), default=0)
            self.selected_elements[element]["atomic_percent"].blockSignals(True)
            self.selected_elements[element]["atomic_percent"].setText(f"{atomic_percent:.4f}")
            self.selected_elements[element]["atomic_percent"].blockSignals(False)
            atomic_ratio = (atomic_percent / max_percent) if max_percent != 0 else 0
            self.selected_elements[element]["atomic_ratio"].blockSignals(True)
            self.selected_elements[element]["atomic_ratio"].setText(f"{atomic_ratio:.4f}")
            self.selected_elements[element]["atomic_ratio"].blockSignals(False)
            weight = total_weight * (weight_percent / 100)
            self.selected_elements[element]["weight"].blockSignals(True)
            self.selected_elements[element]["weight"].setText(f"{weight:.5f}")
            self.selected_elements[element]["weight"].blockSignals(False)
        except ValueError:
            return 0
        self.update_all_percentages()

    def update_ap_ar_wp(self, element):
        self.update_all_percentages()
        if not self.weight_radio.isChecked():
            return  # Do not update if weight mode is not selected
        try:
            total_weight = sum(float(edit["weight"].text() or 0) for edit in self.selected_elements.values())
            max_percent = max((float(edit["atomic_percent"].text() or 0) for edit in self.selected_elements.values()), default=0)

            if total_weight == 0:
                weight_percent = 0
            else:
                weight_percent = float(self.selected_elements[element]["weight"].text()) / total_weight * 100

            atomic_percent = self.weight_to_atomic_percent(element, weight_percent)
            atomic_ratio = (atomic_percent / max_percent) if max_percent != 0 else 0
            self.selected_elements[element]["atomic_percent"].blockSignals(True)
            self.selected_elements[element]["atomic_percent"].setText(f"{atomic_percent:.4f}")
            self.selected_elements[element]["atomic_percent"].blockSignals(False)
            self.selected_elements[element]["atomic_ratio"].blockSignals(True)
            self.selected_elements[element]["atomic_ratio"].setText(f"{atomic_ratio:.4f}")
            self.selected_elements[element]["atomic_ratio"].blockSignals(False)
            self.selected_elements[element]["weight_percent"].blockSignals(True)
            self.selected_elements[element]["weight_percent"].setText(f"{weight_percent:.4f}")
            self.selected_elements[element]["weight_percent"].blockSignals(False)
            self.total_weight_edit.blockSignals(True)
            self.total_weight_edit.setText(f"{total_weight:.5f}")
            self.total_weight_edit.blockSignals(False)
        except ValueError:
            self.show_warning("Invalid input", "Please enter a valid number.")
            return 0
        self.update_all_percentages()
    
    def update_weight(self, element):
        self.update_all_percentages()
        try:
            if element in self.selected_elements:
                weight_percent = float(self.selected_elements[element]["weight_percent"].text() or 0)
                total_weight = float(self.total_weight_edit.text() or 0)
                weight = total_weight * (weight_percent / 100)
                self.selected_elements[element]["weight"].blockSignals(True)
                self.selected_elements[element]["weight"].setText(f"{weight:.5f}")
                self.selected_elements[element]["weight"].blockSignals(False)
        except ValueError:
            self.show_warning("Invalid input", "Please enter a valid number.")
            return 0
        self.update_all_percentages()
    
    def atomic_to_weight_percent(self, element, atomic_percent):
        atomic_weight = self.engine.get_atomic_weight(element)
        total_atomic_weight = sum(self.engine.get_atomic_weight(el) * float(self.selected_elements[el]["atomic_percent"].text() or 0) for el in self.selected_elements)
        if total_atomic_weight == 0:
            return 0  # Avoid division by zero
        weight_percent = (atomic_weight * atomic_percent) / total_atomic_weight * 100
        return weight_percent

    def weight_to_atomic_percent(self, element, weight_percent):
        atomic_weight = self.engine.get_atomic_weight(element)
        total_weight = sum((float(self.selected_elements[el]["weight_percent"].text() or 0) / self.engine.get_atomic_weight(el)) for el in self.selected_elements)
        if total_weight == 0:
            return 0  # Avoid division by zero
        atomic_percent = (weight_percent / atomic_weight) / total_weight * 100
        return atomic_percent
    
    def show_warning(self, title, message):
        self.status_label.setText(f"<b>{title}: </b>{message}")
        self.status_label.setObjectName("status_error")
        self.status_label.setStyleSheet("""
            QLabel {
                background-color: none; 
                color: #ba1b23; 
                border-radius: 0px;
                font-size: 10pt;
                padding: 2px;
            }""")
        self.status_label.show()
        # Clear status message (5 seconds)
        QTimer.singleShot(1300, lambda: self.status_label.hide())

    def toggle_input_mode(self):
        if self.comp_range_radio.isChecked():
            for edits in self.selected_elements.values():
                edits["atomic_percent"].setVisible(True)
                edits["atomic_percent"].setEnabled(True)
                edits["atomic_percent"].setFixedSize(90, 24)
                edits["atomic_percent"].setText("5")
                edits["atomic_ratio"].setVisible(False)
                edits["atomic_ratio"].setEnabled(False)
                edits["weight_percent"].setVisible(False)
                edits["weight_percent"].setEnabled(False)
                self.total_weight_edit.setVisible(False)
                self.total_weight_edit.setEnabled(False)
                edits["weight"].setVisible(False)
                edits["weight"].setEnabled(False)
                edits["to"].setVisible(True)
                edits["tw"].setVisible(True)
                if "atomic_end" in edits:
                    edits["atomic_end"].setVisible(True)
                    edits["atomic_end"].setEnabled(True)
            self.filter_button.setVisible(True)
            self.filter_button.setEnabled(True)
            self.at_percent_radio.setStyleSheet("padding-left: 164px;")
            self.at_percent_radio.setVisible(True)
            self.at_percent_radio.setChecked(True)
            self.at_percent_radio.setEnabled(False)
            self.at_percent_radio.setText("Set at% range")
            self.at_percent_radio.setFixedWidth(435)
            self.at_ratio_radio.setVisible(False)
            self.wt_percent_radio.setVisible(False)
            self.wt_percent_radio.setChecked(False)
            self.weight_radio.setVisible(False)
            self.weight_radio.setChecked(False)
            self.total_row.setVisible(False)
            self.step_size_container.setVisible(True)
        elif self.single_comp_radio.isChecked():
            self.at_percent_radio.setStyleSheet("padding-left: 33px;")
            for edits in self.selected_elements.values():
                edits["atomic_percent"].setVisible(True)
                edits["atomic_percent"].setFixedSize(73, 24)
                edits["atomic_ratio"].setVisible(True)
                edits["weight_percent"].setVisible(True)
                self.total_weight_edit.setVisible(True)
                edits["weight"].setVisible(True)
                edits["to"].setVisible(False)
                edits["tw"].setVisible(False)
                if "atomic_end" in edits:
                    edits["atomic_end"].setVisible(False)
            self.calculate_button.setText("Calculate")
            self.filter_button.setVisible(False)
            self.filter_button.setEnabled(False)
            self.at_percent_radio.setVisible(True)
            self.at_percent_radio.setEnabled(True)
            self.at_percent_radio.setText("at%")
            self.at_percent_radio.setFixedWidth(105)
            self.at_ratio_radio.setVisible(True)
            self.wt_percent_radio.setVisible(True)
            self.weight_radio.setVisible(True)
            self.total_row.setVisible(True)
            self.step_size_container.setVisible(False)
            if self.at_percent_radio.isChecked():
                for edits in self.selected_elements.values():
                    edits["atomic_percent"].setEnabled(True)
                    edits["atomic_ratio"].setEnabled(False)
                    edits["weight_percent"].setEnabled(False)
                    edits["weight"].setEnabled(False)
                    self.total_weight_edit.setEnabled(True)
                self.update_all_percentages()
            elif self.at_ratio_radio.isChecked():
                for edits in self.selected_elements.values():
                    edits["atomic_percent"].setEnabled(False)
                    edits["atomic_ratio"].setEnabled(True)
                    edits["weight_percent"].setEnabled(False)
                    edits["weight"].setEnabled(False)
                    self.total_weight_edit.setEnabled(True)
            elif self.wt_percent_radio.isChecked():
                for edits in self.selected_elements.values():
                    edits["atomic_percent"].setEnabled(False)
                    edits["atomic_ratio"].setEnabled(False)
                    edits["weight_percent"].setEnabled(True)
                    edits["weight"].setEnabled(False)
                    self.total_weight_edit.setEnabled(True)
            elif self.weight_radio.isChecked():
                for edits in self.selected_elements.values():
                    edits["atomic_percent"].setEnabled(False)
                    edits["atomic_ratio"].setEnabled(False)
                    edits["weight_percent"].setEnabled(False)
                    edits["weight"].setEnabled(True)
                    self.total_weight_edit.setEnabled(False)

    def update_all_atomic_percent(self, text):
        # updates all atomic_percent line edits with the value from from_at_edit
        for edits in self.selected_elements.values():
            edits["atomic_percent"].setText(text)

    def update_all_atomic_end(self, text):
        # updates all atomic_end line edits with the value from to_at_edit
        for edits in self.selected_elements.values():
            edits["atomic_end"].setText(text)

    def toggle_element(self, element, button):
        if button.isChecked():
            self.select_element(element)
        else:
            self.deselect_element(element)

    def select_element(self, element):
        if element not in self.selected_elements:
            self.add_selected_element_to_frame(element)

    def deselect_element(self, element):
        if element in self.selected_elements:
            # Remove the widgets associated with the element
            edits = self.selected_elements.pop(element)
            for widget in edits.values():
                widget.deleteLater()

            # Remove the container widget from the layout
            for i in reversed(range(self.selected_elements_container.count())):
                container = self.selected_elements_container.itemAt(i).widget()
                curr_label = container.layout().itemAt(0).widget().text()
                if curr_label == element:
                    self.selected_elements_container.takeAt(i).widget().deleteLater()
                    break
            if self.single_comp_radio.isChecked():
                total_elements = len(self.selected_elements)
                if total_elements > 0:
                    equ_atomic_percent = 100 / total_elements
                    for edits in self.selected_elements.values():
                        edits["atomic_percent"].blockSignals(True)
                        edits["atomic_percent"].setText(f"{equ_atomic_percent:.2f}")
                        edits["atomic_percent"].blockSignals(False)
            elif self.comp_range_radio.isChecked():
                for edits in self.selected_elements.values():
                    edits["atomic_percent"].setText("5")
                self.update_all_percentages()

    def clear_selected_elements(self):
        for button in self.periodic_table.buttons.values():
            button.setChecked(False)
        for i in reversed(range(self.selected_elements_container.count())):
            self.selected_elements_container.itemAt(i).widget().setParent(None)
        self.selected_elements.clear()
        self.total_atomic_label.setText("0.00")
        self.total_weight_percent_label.setText("0.00")

    def on_calculate_button_click(self):
        self.stop_requested = False
        if self.single_comp_radio.isChecked():
            self.update_alloy_info()
        else:
            self.generate_alloy_compositions()

    def show_restrictions_window(self):
        dialog = QDialog(self)
        dialog.setFixedSize(378, 528)
        dialog.setWindowTitle("Filter results")
        layout_left = QVBoxLayout()
        layout_left.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout_right = QVBoxLayout()
        layout_right.setAlignment(Qt.AlignmentFlag.AlignTop)

        properties = ["density", "delta", "gamma", "enthalpy_of_mixing", "vec", "mixing_entropy", "melting_temp", "omega"]
        properties_label = ["Density (g/cm³)", "δ", "γ", "ΔHₘᵢₓ (kJ/mol)", "VEC", "ΔSₘᵢₓ (kJ/mol)", "Tₘ (K)", "Ω"]
        self.num_res_edits = {} # Numerical restrictions' edits

        for property, property_label in zip(properties, properties_label):
            checkbox = QCheckBox(property_label)
            checkbox.stateChanged.connect(lambda _, prop=property: self.toggle_restriction(prop))
            layout_left.addWidget(checkbox)
            min_edit = default_line_edit("", 73, 24)
            min_edit.setProperty("class", "gray10_line_edit")
            min_edit.setPlaceholderText("Min")
            min_edit.setEnabled(False)
            max_edit = default_line_edit("", 73, 24)
            max_edit.setProperty("class", "gray10_line_edit")
            max_edit.setPlaceholderText("Max")
            max_edit.setEnabled(False)
            hlayout = QHBoxLayout()
            hlayout.addWidget(min_edit)
            hlayout.addWidget(max_edit)
            layout_left.addLayout(hlayout)
            self.num_res_edits[property] = {
                "checkbox": checkbox,
                "min": min_edit,
                "max": max_edit,
            }

        cstrs = ["FCC", "BCC", "BCC + FCC", "HCP"]
        models = ["SS", "IM", "Mixed"]
        dropdown_labels = ["Crystal Str.", "Model 1", "Model 2", "Model 3", "Model 4", "Model 5", "Model 6"]
        dropdown_restrictions = {"cstr": cstrs, "model1": models, "model2": models, "model3": models, "model4": models,
                                 "model6": models, "model7": models}
        self.cat_res_edits = {} # Categorical restrictions' edits

        for dropdown, dropdown_label in zip(dropdown_restrictions, dropdown_labels):
            checkbox = QCheckBox(dropdown_label)
            checkbox.stateChanged.connect(lambda _, prop=dropdown: self.toggle_restriction(prop))
            layout_right.addWidget(checkbox)
            combobox = QComboBox()
            combobox.setFixedSize(160, 24)
            combobox.addItems(dropdown_restrictions[dropdown])
            combobox.setEnabled(False)
            layout_right.addWidget(combobox)
            self.cat_res_edits[dropdown] = {
                "checkbox": checkbox,
                "dropdown": combobox}

        layout = QHBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        cancel_button = QPushButton("Cancel")
        cancel_button.setStyleSheet("""
            QPushButton {
                text-align: left;   
                padding-left: 18px;
                padding-bottom: 20px;
            }
        """)
        cancel_button.setFixedSize(189, 64)
        cancel_button.setProperty("class", "secondary_button")
        cancel_button.clicked.connect(dialog.reject)
        apply_button = QPushButton("Apply")
        apply_button.setStyleSheet("""
            QPushButton {
                text-align: left;   
                padding-left: 18px;
                padding-bottom: 20px;
            }
        """)
        apply_button.setFixedSize(189, 64)
        apply_button.setProperty("class", "primary_button")
        apply_button.clicked.connect(lambda: self.apply_restrictions(dialog))
        layout.addLayout(layout_left)
        layout.addItem((QSpacerItem(20, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
        layout.addLayout(layout_right)
        container = QVBoxLayout(dialog)
        container.setContentsMargins(0, 0, 0, 0)
        container.addLayout(layout)
        button_layout = QHBoxLayout()
        button_layout.setSpacing(0)
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(apply_button)
        container.addLayout(button_layout)

        dialog.setLayout(container)
        dialog.exec()

    def toggle_restriction(self, property):
        if property in self.num_res_edits:
            if self.num_res_edits[property]["checkbox"].isChecked():
                self.num_res_edits[property]["min"].setEnabled(True)
                self.num_res_edits[property]["max"].setEnabled(True)
            else:
                self.num_res_edits[property]["min"].setEnabled(False)
                self.num_res_edits[property]["max"].setEnabled(False)
        elif property in self.cat_res_edits:
            if self.cat_res_edits[property]["checkbox"].isChecked():
                self.cat_res_edits[property]["dropdown"].setEnabled(True)
            else:
                self.cat_res_edits[property]["dropdown"].setEnabled(False)

    def apply_restrictions(self, dialog):
        self.restriction_values = {}
        for property, restrictions in self.num_res_edits.items():
            if restrictions["checkbox"].isChecked():
                self.restriction_values[property] = {
                    "min": restrictions["min"].text(),
                    "max": restrictions["max"].text()
                }
        for property, restrictions in self.cat_res_edits.items():
            if restrictions["checkbox"].isChecked():
                self.restriction_values[property] = restrictions["dropdown"].currentText()
        dialog.accept()

    def generate_alloy_compositions(self):
        selected_elements = {}
        step_size = float(self.step_size_edit.text())
        try:
            for element, edits in self.selected_elements.items():
                try:
                    atomic_percent = float(edits["atomic_percent"].text())
                    if self.comp_range_radio.isChecked() and "atomic_end" in edits:
                        atomic_percent_end = float(edits["atomic_end"].text())
                        selected_elements[element] = (atomic_percent, atomic_percent_end)
                    else:
                        if atomic_percent <= 0:
                            raise ValueError("Percentage must be positive.")
                        selected_elements[element] = (atomic_percent, atomic_percent)
                except ValueError:
                    QMessageBox.critical(self, "Input Error", f"Invalid input for {element}")
                    return

            self.dialog = QDialog(self)
            self.dialog.setFixedSize(300, 120)
            self.dialog.setWindowTitle("Generating Compositions")
            layout = QVBoxLayout(self.dialog)
            self.progress_label = QLabel("Generating compositions, please wait...", self.dialog)
            layout.addWidget(self.progress_label)
            self.progress_bar = QProgressBar(self.dialog)
            self.progress_bar.setFixedHeight(5)
            self.progress_bar.setRange(0, 0)  # Indeterminate mode
            layout.addWidget(self.progress_bar)
            layout.addItem((QSpacerItem(0, 40, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
            self.dialog.setLayout(layout)
            self.dialog.show()

            self.composition_worker = CompositionGenerationWorker(selected_elements, step_size)
            self.composition_worker.compositions_ready.connect(self.on_compositions_ready)
            self.composition_worker.start()

        except ValueError:
            self.show_warning("Error", "Not enough data.")

    def on_compositions_ready(self, compositions):
        self.dialog.accept()
        self.calculate_alloys(compositions)

    def load_compositions_from_excel(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Excel File", "", "Excel Files (*.xlsx *.xls)")
        if file_path:
            compositions = self.read_compositions_from_excel(file_path)
            self.calculate_alloy_parameters(compositions)


    def read_compositions_from_excel(self, file_path):
        try:
            df = pd.read_excel(file_path)

            compositions = []
            composition_columns = self.find_composition_columns(df)

            for index, row in df.iterrows():
                composition = self.parse_composition_row(row, composition_columns)
                compositions.append(composition)

            return compositions
        except Exception as e:
            print(f"Error reading Excel file: {e}")
            return []

    def parse_composition_row(self, row, composition_columns):
        composition = {}
        for col in composition_columns:
            elements = re.findall(r'([A-Za-z]+)(\d*\.?\d*)', str(row[col]))
            total_ratio = sum(float(ratio) for _, ratio in elements)
            if total_ratio == 100:
                composition = {element: float(ratio) / 100.0 for element, ratio in elements}
            else:
                composition = {element: float(ratio) / total_ratio * 100.0 for element, ratio in elements}
        return composition

    def find_composition_columns(self, df):
        possible_headers = [
            "FORMULA",
            "IDENTIFIER",
            "ALLOY",
            "COMPOSITION",
            "COMPOSITION: Formula",
            "COMPOSITION: Elements"
            # Add more possible headers as needed
        ]

        composition_columns = []
        for col in df.columns:
            for header in possible_headers:
                if header.lower() in str(col).lower():
                    composition_columns.append(col)
                    break

        return composition_columns

    def process_compositions(self, compositions):
        for comp in compositions:
            print(comp)

    def calculate_alloy_parameters(self, compositions):
        try:
            # Call your existing calculate_alloys function here
            self.calculate_alloys(compositions)  # Adjust this based on your existing implementation

        except Exception as e:
            print(f"Error calculating alloy parameters: {e}")

    def calculate_alloys(self, compositions):
        self.dialog = QDialog(self)
        self.dialog.setFixedSize(300, 120)
        self.dialog.setWindowTitle("Calculating Alloys")
        layout = QVBoxLayout(self.dialog)

        self.progress_label = QLabel(self.dialog)
        layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar(self.dialog)
        self.progress_bar.setFixedHeight(5)
        self.progress_bar.setMaximum(len(compositions))
        layout.addWidget(self.progress_bar)

        self.time_label = QLabel(self.dialog)
        layout.addWidget(self.time_label)

        stop_button = QPushButton("Stop", self.dialog)
        stop_button.setProperty("class", "danger_button")
        stop_button.setFixedSize(100, 38)
        stop_button.clicked.connect(self.stop_calculation)
        layout.addWidget(stop_button, alignment=Qt.AlignmentFlag.AlignRight)

        self.dialog.setLayout(layout)
        self.dialog.show()

        self.worker = AlloyCalculationWorker(compositions, self.engine, self.restriction_values)
        self.worker.update_progress.connect(self.update_progress)
        self.worker.all_results_ready.connect(self.on_calculation_finished)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def update_progress(self, current, total, estimated_time):
        self.progress_bar.setValue(current)
        self.progress_bar.setFixedHeight(5)
        self.progress_label.setText(f"{current} of {total} alloys have been calculated")
        self.time_label.setText(f"Estimated time remaining: {estimated_time:.2f} seconds")
        self.time_label.setStyleSheet("color: #c6c6c6;")

    def on_calculation_finished(self, temp_file_name, count_meeting_criteria):
        self.temp_file_name = temp_file_name
        self.count_meeting_criteria = count_meeting_criteria
        self.progress_bar.setRange(0, 0)  # Set to indeterminate mode
        self.progress_bar.setFixedHeight(5)
        self.progress_label.setText("Processing results, please wait...")
        QTimer.singleShot(0, self.handle_all_results)

    def on_worker_finished(self):
        self.dialog.accept()

    def handle_all_results(self):
        if self.count_meeting_criteria <= 20000:
            self.load_results_to_table(self.temp_file_name)
        else:
            self.save_results_to_excel()

    def load_results_to_table(self, temp_file_name):
        with open(temp_file_name, 'r') as temp_file:
            results = json.load(temp_file)
            for values, alloy_name in results:
                row_position = self.alloy_table.rowCount()
                self.alloy_table.insertRow(row_position)
                self.alloy_table.setItem(row_position, 0, QTableWidgetItem(alloy_name))
                self.alloy_table.setItem(row_position, 1, QTableWidgetItem("{:.6f}".format(values["density"])))
                self.alloy_table.setItem(row_position, 2, QTableWidgetItem("{:.6f}".format(values["delta"])))
                self.alloy_table.setItem(row_position, 3, QTableWidgetItem("{:.6f}".format(values["gamma"])))
                self.alloy_table.setItem(row_position, 4, QTableWidgetItem("{:.6f}".format(values["enthalpy_of_mixing"])))
                self.alloy_table.setItem(row_position, 5, QTableWidgetItem("{:.2f}".format(values["vec"])))
                self.alloy_table.setItem(row_position, 6, QTableWidgetItem("{:.6f}".format(values["mixing_entropy"])))
                self.alloy_table.setItem(row_position, 7, QTableWidgetItem("{:.2f}".format(values["melting_temp"])))
                self.alloy_table.setItem(row_position, 8, QTableWidgetItem("{:.6f}".format(values["omega"])))
                self.alloy_table.setItem(row_position, 9, QTableWidgetItem(values["cstr"]))
                self.alloy_table.setItem(row_position, 10, QTableWidgetItem(values["model1"]))
                self.alloy_table.setItem(row_position, 11, QTableWidgetItem(values["model2"]))
                self.alloy_table.setItem(row_position, 12, QTableWidgetItem(values["model3"]))
                self.alloy_table.setItem(row_position, 13, QTableWidgetItem(values["model4"]))
                self.alloy_table.setItem(row_position, 14, QTableWidgetItem(values["model6"]))
                self.alloy_table.setItem(row_position, 15, QTableWidgetItem(values["model7"]))
        os.remove(temp_file_name)  # Delete the temporary file

    def save_results_to_excel(self):
        selected_elements_str = ''.join(self.selected_elements.keys())
        current_time_str = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
        file_name = f"{selected_elements_str}_{current_time_str}.xlsx"
        
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if not directory:
            self.on_excel_write_finished("")  # Handle cancel case
            return

        file_path = os.path.join(directory, file_name)
        
        headers = ["Alloy", "Density (g/cm³)", "δ", "γ", "ΔHₘᵢₓ (kJ/mol)", "VEC", "ΔSₘᵢₓ (kJ/mol)", "Tₘ (K)", 
                   "Ω", "Crystal Str.", "Model 1", "Model 2", "Model 3", "Model 4", "Model 5", "Model 6"]

        self.excel_worker = ExcelWriterWorker(self.temp_file_name, file_path, headers)
        self.excel_worker.progress.connect(self.update_progress)
        self.excel_worker.finished.connect(self.on_excel_write_finished)
        self.show_progress_dialog()
        self.excel_worker.start()

    def show_progress_dialog(self):
        self.dialog = QDialog(self)
        self.dialog.setFixedSize(300, 120)
        self.dialog.setWindowTitle("Saving to Excel")
        layout = QVBoxLayout(self.dialog)
        self.progress_label = QLabel(self.dialog)
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar(self.dialog)
        self.progress_bar.setFixedHeight(5)
        layout.addWidget(self.progress_bar)
        self.dialog.setLayout(layout)
        self.dialog.show()

    def update_progress(self, processed, total):
        self.progress_label.setText(f"Processed {processed} of {total}")
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(processed)

    def on_excel_write_finished(self, file_path):
        self.dialog.accept()
        if os.path.exists(self.temp_file_name):
            os.remove(self.temp_file_name)  # Delete the temporary file
        if file_path:
            QMessageBox.information(self, "Save to Excel", f"Alloy information saved to {file_path}")
        else:
            QMessageBox.information(self, "Save to Excel", "Excel file saving was canceled.")

    def stop_calculation(self):
        if self.calculation_worker:
            self.calculation_worker.stop_requested = True
        self.dialog.reject()

    def update_alloy_info(self):
        alloy_name = ""
        selected_elements = {}
        for element, edits in self.selected_elements.items():
            try:
                atomic_percent = float(edits["atomic_percent"].text())
                if atomic_percent <= 0:
                    raise ValueError("Percentage must be positive.")
                selected_elements[element] = atomic_percent / 100
                alloy_name += f"{element}{MDLHEAPP._to_subscript(str(int(atomic_percent)))}"
            except ValueError:
                QMessageBox.critical(self, "Input Error", f"Invalid input for {element}")
                return

        try:
            values, mets_criteria = self.engine.calculate(selected_elements ,restriction_values=None)
            row_position = self.alloy_table.rowCount()
            self.alloy_table.insertRow(row_position)
            self.alloy_table.setItem(row_position, 0, QTableWidgetItem(alloy_name))
            self.alloy_table.setItem(row_position, 1, QTableWidgetItem("{:.6f}".format(values["density"])))
            self.alloy_table.setItem(row_position, 2, QTableWidgetItem("{:.6f}".format(values["delta"])))
            self.alloy_table.setItem(row_position, 3, QTableWidgetItem("{:.6f}".format(values["gamma"])),)
            self.alloy_table.setItem(row_position, 4, QTableWidgetItem("{:.6f}".format(values["enthalpy_of_mixing"])))
            self.alloy_table.setItem(row_position, 5, QTableWidgetItem("{:.2f}".format(values["vec"])))
            self.alloy_table.setItem(row_position, 6, QTableWidgetItem("{:.6f}".format(values["mixing_entropy"])))
            self.alloy_table.setItem(row_position, 7, QTableWidgetItem("{:.2f}".format(values["melting_temp"])))
            self.alloy_table.setItem(row_position, 8, QTableWidgetItem("{:.6f}".format(values["omega"])))
            self.alloy_table.setItem(row_position, 9, QTableWidgetItem(values["cstr"]))
            self.alloy_table.setItem(row_position, 10, QTableWidgetItem(values["model1"]))
            self.alloy_table.setItem(row_position, 11, QTableWidgetItem(values["model2"]))
            self.alloy_table.setItem(row_position, 12, QTableWidgetItem(values["model3"]))
            self.alloy_table.setItem(row_position, 13, QTableWidgetItem(values["model4"]))
            self.alloy_table.setItem(row_position, 14, QTableWidgetItem(values["model6"]))
            self.alloy_table.setItem(row_position, 15, QTableWidgetItem(values["model7"]))
        except ValueError:
            self.show_warning("Error", "Not enough data.")
        return 0

    def clear_alloy_info(self):
        self.alloy_table.setRowCount(0)

    def save_to_excel(self):
        settings = self.settings.load_settings()
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if not directory:
            return
        file_path = os.path.join(directory, "alloy_info.xlsx")

        data = []
        for row in range(self.alloy_table.rowCount()):
            row_data = [self.alloy_table.item(row, col).text() for col in range(self.alloy_table.columnCount())]
            data.append(row_data)

        df = pd.DataFrame(data, columns=["Alloy", "Density (g/cm³)", "δ", "γ", "ΔHₘᵢₓ (kJ/mol)", "VEC", "ΔSₘᵢₓ (kJ/mol)", "Tₘ (K)", 
                                         "Ω", "Crystal Str.", "Model 1", "Model 2", "Model 3", "Model 4", "Model 5", "Model 6"])
        df.to_excel(file_path, index=False)
        QMessageBox.information(self, "Save to Excel", f"Alloy information saved to {file_path}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("IBM Plex Sans"))
    window = MDLHEAPP()
    window.showMaximized()
    sys.exit(app.exec())