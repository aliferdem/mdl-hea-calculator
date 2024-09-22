# HEA Phase Predictor
# © 2024 Metals Development Laboratory, Department of Metallurgical and Materials Engineering, Middle East Technical University.
# All rights reserved.
# This software is proprietary and confidential.
# Unauthorized copying of this file and accompanying files, via any medium, is strictly prohibited.
# Licensed only for use by members of Metals Development Laboratory.

# This version of the HEA Phase Predictor is based on an original application, HEACalculator, developed by Doguhan Sariturk.
# Significant improvements and changes were made to enhance its functionality, with assistance from ChatGPT, 
# for use by members of the Metals Development Laboratory.

__author__ = "Ali Fethi Erdem"
__version__ = "1.0"
__email__ = "erdem.alifethi@gmail.com"
__license__ = "Proprietary - For use only by members of the Metals Development Laboratory"
__credits__ = "Original version developed by Doguhan Sariturk under the name of HEACalculator"

import json
import tempfile
import itertools
import time
import os
import re
import sys
import pandas as pd
from datetime import datetime
import xlsxwriter
from PySide6.QtCore import (Qt, QTimer, QLocale, QThread, Signal, QSize, QPoint, QEvent)
from PySide6.QtGui import (QPixmap, QDoubleValidator, QIcon, QFont, QMouseEvent)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog,
    QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QSpacerItem,
    QSizePolicy, QRadioButton, QScrollArea,
    QStatusBar, QProgressBar, QDialog,
    QComboBox)

from engine import Engine

class Settings:
    def __init__(self):
        self.settings_file = "user_settings.json"
        self.default_settings = {"theme": "dark"}  # Default theme is dark
        
        # Load settings from file or use defaults if file doesn't exist
        if os.path.exists(self.settings_file):
            with open(self.settings_file, "r") as f:
                self.settings = json.load(f)
        else:
            self.settings = self.default_settings

    def get_theme(self):
        return self.settings.get("theme", "dark")

    def set_theme(self, theme):
        self.settings["theme"] = theme
        with open(self.settings_file, "w") as f:
            json.dump(self.settings, f)

class AlloyCalculationWorker(QThread):
    update_progress = Signal(int, int, float)
    finished = Signal()
    all_results_ready = Signal(str, int)  # Added count parameter

    def __init__(self, compositions, engine, restriction_values):
        super().__init__()
        self.compositions = compositions
        self.engine = engine
        self.restriction_values = restriction_values
        self.stop_requested = False
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.json')
        
    def run(self):
        start_time = time.time()
        results = []
        count_meeting_criteria = 0
        for i, composition in enumerate(self.compositions):
            if self.stop_requested:
                break
            alloy_name = "".join(f"{el}{MDLHEAPP._to_subscript(str(int(percent)))}" for el, percent in composition.items())
            composition = {k: v / 100 for k, v in composition.items()}
            values, meets_criteria = self.engine.calculate(composition, self.restriction_values)
            if meets_criteria:
                results.append((values, alloy_name))
                count_meeting_criteria += 1
            elapsed_time = time.time() - start_time
            estimated_time = elapsed_time / (i + 1) * (len(self.compositions) - (i + 1))
            self.update_progress.emit(i + 1, len(self.compositions), estimated_time)

        json.dump(results, self.temp_file)
        self.temp_file.close()
        self.all_results_ready.emit(self.temp_file.name, count_meeting_criteria)
        self.finished.emit()

class CompositionGenerationWorker(QThread):
    compositions_ready = Signal(list)

    def __init__(self, selected_elements, step_size):
        super().__init__()
        self.selected_elements = selected_elements
        self.step_size = step_size

    def run(self):
        compositions = []
        keys, ranges = zip(*self.selected_elements.items())
        ranges = [list(range(int(start), int(end) + 1, int(self.step_size))) for start, end in ranges]
        for values in itertools.product(*ranges):
            composition = dict(zip(keys, values))
            if sum(composition.values()) == 100:
                compositions.append(composition)
        self.compositions_ready.emit(compositions)

class ExcelWriterWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(str)
    
    def __init__(self, file_name, file_path, headers):
        super().__init__()
        self.file_name = file_name
        self.file_path = file_path
        self.headers = headers

    def run(self):
        workbook = xlsxwriter.Workbook(self.file_path)
        worksheet = workbook.add_worksheet()
        
        # Write headers
        for col_num, header in enumerate(self.headers):
            worksheet.write(0, col_num, header)
        
        row = 1
        chunk_size = 100
        total_processed = 0
        total_chunks = sum(1 for _ in read_results_in_chunks(self.file_name, chunk_size))
        
        for chunk in read_results_in_chunks(self.file_name, chunk_size):
            for values, alloy_name in chunk:
                row_data = [
                    alloy_name,
                    values["density"],
                    values["delta"],
                    values["gamma"],
                    values["enthalpy_of_mixing"],
                    values["vec"],
                    values["mixing_entropy"],
                    values["melting_temp"],
                    values["omega"],
                    values["cstr"],
                    values["model1"],
                    values["model2"],
                    values["model3"],
                    values["model4"],
                    values["model6"],
                    values["model7"]
                ]
                for col_num, data in enumerate(row_data):
                    worksheet.write(row, col_num, data)
                row += 1
                total_processed += 1
                self.progress.emit(total_processed, total_chunks * chunk_size)
        
        workbook.close()
        self.finished.emit(self.file_path)

def read_results_in_chunks(file_name, chunk_size=100):
    with open(file_name, 'r') as file:
        data = json.load(file)
        for i in range(0, len(data), chunk_size):
            yield data[i:i + chunk_size]

class MDLHEAPP(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("MDL | HEA Phase Predictor")
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.resize(1645, 800)
        self.settings = Settings()

        self.composition_worker = None
        self.calculation_worker = None
        self.dialog = None

        # Engine
        self.engine = Engine()

        self.logo_label = QLabel()
        self.logo_label.setPixmap(QPixmap("ui/logo_dark.svg"))

        self.setWindowIcon(QIcon("ui/icons/logo_icon.ico"))

        self.pTable_buttons = {}
        self.selected_elements = {}

        self.single_radio = QRadioButton("Single Composition")
        self.single_radio.setObjectName("single_radio")
        self.single_radio.setChecked(True)
        self.single_radio.setFixedHeight(35)

        self.range_radio = QRadioButton("Composition Range")
        self.range_radio.setObjectName("range_radio")
        self.range_radio.setFixedHeight(35)

        self.at_percent_radio = QRadioButton("At. %")
        self.at_percent_radio.setChecked(True)
        self.at_percent_radio.setFixedHeight(40)
        self.at_ratio_radio = QRadioButton("At. Ratio")
        self.at_ratio_radio.setFixedHeight(40)

        self.wt_percent_radio = QRadioButton("Wt. %")
        self.wt_percent_radio.setFixedHeight(40)

        self.weight_radio = QRadioButton("Weight (g)")
        self.weight_radio.setFixedSize(130, 40)

        self.total_label = QLabel("Total:")
        self.total_label.setStyleSheet("font-weight: bold;")
        self.total_atomic_label = QLabel("")
        self.total_weight_percent_label = QLabel("")
        self.total_weight_edit = self.validated_line_edit("0")
        self.total_weight_edit.setProperty("class", "primary_text")
        self.total_weight_edit.setFixedSize(80, 30)
        self.step_size_label = QLabel("Step Size:")
        self.step_size_label.setStyleSheet("font-weight: bold;")
        self.step_size_edit = self.validated_line_edit("5")
        self.step_size_edit.setProperty("class", "primary_text")
        self.step_size_edit.setFixedSize(80, 30)

        self.restrict_button = QPushButton("Restrict")
        self.restrict_button.setProperty("class", "danger_button")
        self.restrict_button.setFixedSize(120, 38)
        self.restrict_button.setLayoutDirection(Qt.RightToLeft)
        self.restrict_button.setIcon(QIcon("ui/icons/filter--edit.svg"))
        self.restrict_button.setIconSize(QSize(20, 20))
        self.restrict_button.clicked.connect(self.show_restrictions_window)

        self.restriction_values = {}

        self.initUI()

    def _read(self, file_name: str):
        with open(file_name, "r") as f:
            return json.load(f)

    def _to_subscript(num_str):
        subscript_map = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
        return num_str.translate(subscript_map)

    def initUI(self):
        current_theme = self.settings.get_theme()

        main_widget = QWidget()
        parent_layout = QVBoxLayout(main_widget)
        parent_layout.setContentsMargins(0, 0, 0, 0)

        global_header_layout = QHBoxLayout()
        global_header_layout.setContentsMargins(10, 0, 0, 0)
        global_header_layout.setSpacing(0)
        self.global_header_widget = QWidget()
        self.global_header_widget.setProperty("class", "global_header")
        self.global_header_widget.setLayout(global_header_layout)
        self.global_header_widget.setFixedHeight(40)

        global_header_layout.addWidget(self.logo_label)

        self.upload_button = QPushButton(self)
        self.upload_button.setProperty("class", "header_button")
        self.upload_button.setFixedSize(39, 39)
        self.upload_button.setIcon(QIcon("ui/icons/table--shortcut.svg"))
        self.upload_button.setIconSize(QSize(20, 20))
        self.upload_button.setToolTip("Upload an Excel file")
        self.upload_button.clicked.connect(self.load_compositions_from_excel)
        global_header_layout.addWidget(self.upload_button)

        self.switch_theme_button = QPushButton(self)
        self.switch_theme_button.setProperty("class", "header_button")
        self.switch_theme_button.setFixedSize(39, 39)
        self.switch_theme_button.setIconSize(QSize(20, 20))
        self.switch_theme_button.clicked.connect(self.switch_theme)
        global_header_layout.addWidget(self.switch_theme_button)

        self.info_button = QPushButton(self)
        self.info_button.setProperty("class", "header_button")
        self.info_button.setFixedSize(39, 39)
        self.info_button.setIcon(QIcon("ui/icons/information_dark.svg"))
        self.info_button.setToolTip("Information")
        self.info_button.setIconSize(QSize(20, 20))
        self.info_button.clicked.connect(self.show_info)
        global_header_layout.addWidget(self.info_button)

        self.minimize_button = QPushButton(self)
        self.minimize_button.setProperty("class", "header_button")
        self.minimize_button.setFixedSize(39, 39)
        self.minimize_button.setIcon(QIcon("ui/icons/subtract.svg"))
        self.minimize_button.clicked.connect(self.window().showMinimized)
        global_header_layout.addWidget(self.minimize_button)
        
        self.maximize_button = QPushButton(self)
        self.maximize_button.setProperty("class", "header_button")
        self.maximize_button.setFixedSize(39, 39)
        self.maximize_button.setIcon(QIcon("ui/icons/maximize.svg"))
        self.maximize_button.setIconSize(QSize(20, 20))
        self.maximize_button.clicked.connect(self.window().showMaximized)
        global_header_layout.addWidget(self.maximize_button)

        self.normal_button = QPushButton(self)
        self.normal_button.setProperty("class", "header_button")
        self.normal_button.setFixedSize(39, 39)
        self.normal_button.setIcon(QIcon("ui/icons/minimize.svg"))
        self.normal_button.setIconSize(QSize(20, 20))
        self.normal_button.clicked.connect(self.window().showNormal)
        global_header_layout.addWidget(self.normal_button)
        
        self.close_button = QPushButton(self)
        self.close_button.setProperty("class", "close_button")
        self.close_button.setFixedSize(39, 39)
        self.close_button.setIcon(QIcon("ui/icons/close.svg"))
        self.close_button.clicked.connect(self.window().close)
        global_header_layout.addWidget(self.close_button)

        parent_layout.addWidget(self.global_header_widget)
        self.old_pos = None

        if current_theme == "dark":
            self.element_colors = self._read("ui/styles/element_colors_dark.json")
            with open("ui/styles/styleSheet_dark.qss", "r") as f:
                self.dark_stylesheet = f.read()
            self.setStyleSheet(self.dark_stylesheet)
            self.switch_theme_button.setIcon(QIcon("ui/icons/light.svg"))
            self.switch_theme_button.setToolTip("Light theme")
            self.info_button.setIcon(QIcon("ui/icons/information_dark.svg"))
        elif current_theme == "light":
            self.element_colors = self._read("ui/styles/element_colors_light.json")
            with open("ui/styles/styleSheet_light.qss", "r") as f:
                self.light_stylesheet = f.read()
            self.setStyleSheet(self.light_stylesheet)
            self.switch_theme_button.setIcon(QIcon("ui/icons/asleep.svg"))
            self.switch_theme_button.setToolTip("Dark theme")
            self.info_button.setIcon(QIcon("ui/icons/information_light.svg"))

        top_layout = QHBoxLayout()

        periodic_layout = QVBoxLayout()

        # Periodic table
        self.table_frame = QGridLayout()
        self.add_elements_to_table()

        periodic_table_widget = QWidget()
        periodic_table_widget.setLayout(self.table_frame)
        periodic_table_widget.setFixedHeight(420) # Default 440
        periodic_layout.addWidget(periodic_table_widget)
        top_layout.addStretch(1)
        top_layout.addLayout(periodic_layout) 

        # Selected elements and their percentages
        selected_frame_widget = QWidget()
        selected_frame_layout = QVBoxLayout(selected_frame_widget)
        selected_frame_layout.setSpacing(0)
        selected_frame_layout.setContentsMargins(0, 0, 0, 0)
        selected_frame_layout.addItem((QSpacerItem(0, 10, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))

        # Radio Buttons
        radio_layout = QHBoxLayout()
        radio_layout.setSpacing(0)
        radio_layout.setContentsMargins(0, 0, 0, 0)

        radio_spacer = QWidget()
        radio_spacer.setFixedWidth(60)
        radio_layout.addItem((QSpacerItem(60, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
        radio_layout.addWidget(self.single_radio, Qt.AlignmentFlag.AlignCenter)
        radio_layout.addWidget(self.range_radio, Qt.AlignmentFlag.AlignCenter)
        radio_layout.addItem((QSpacerItem(60, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))

        selected_frame_layout.addLayout(radio_layout)

        selected_frame_layout.addItem((QSpacerItem(0, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))

        # Add radio buttons and labels to the first row
        first_row = QWidget()
        first_row_layout = QHBoxLayout(first_row)
        first_row_layout.setSpacing(0)
        first_row_layout.setContentsMargins(0, 0, 0, 0)

        first_row_layout.addItem(QSpacerItem(20, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))
        element_label = QLabel("Element")
        element_label.setStyleSheet("font-weight: bold;")
        first_row_layout.addWidget(element_label)

        self.at_percent_radio.setChecked(True)
        first_row_layout.addWidget(self.at_ratio_radio)
        first_row_layout.addWidget(self.at_percent_radio)
        first_row_layout.addWidget(self.wt_percent_radio)
        first_row_layout.addWidget(self.weight_radio)

        self.at_percent_radio.toggled.connect(self.toggle_input_mode)
        self.wt_percent_radio.toggled.connect(self.toggle_input_mode)
        self.weight_radio.toggled.connect(self.toggle_input_mode)
        self.single_radio.toggled.connect(self.toggle_input_mode)
        self.range_radio.toggled.connect(self.toggle_input_mode)

        selected_frame_layout.addWidget(first_row)

        # Selected Elements Container
        self.selected_elements_container = QVBoxLayout()

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setViewportMargins(0, 0, 15, 0)
        scroll_content = QWidget()
        scroll_content.setLayout(self.selected_elements_container)
        scroll_area.setWidget(scroll_content)
        selected_frame_layout.addWidget(scroll_area)
        scroll_content.setFixedWidth(scroll_area.width() - scroll_area.verticalScrollBar().sizeHint().width())
        scroll_area.resizeEvent = lambda event: scroll_content.setFixedWidth(scroll_area.width() - scroll_area.verticalScrollBar().sizeHint().width())
        # Add total percentage labels to the last row
        self.total_row = QWidget()
        total_row_layout = QHBoxLayout(self.total_row)
        total_row_layout.setContentsMargins(10, 10, 10, 0)

        total_row_layout.addItem((QSpacerItem(20, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
        total_row_layout.addWidget(self.total_label)
        total_row_layout.addItem((QSpacerItem(132, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
        total_row_layout.addWidget(self.total_atomic_label)
        total_row_layout.addItem((QSpacerItem(20, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
        total_row_layout.addWidget(self.total_weight_percent_label)
        total_row_layout.addWidget(self.total_weight_edit)
        total_row_layout.addItem((QSpacerItem(26, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))

        selected_frame_layout.addWidget(self.total_row)

        clear_selected_button = QPushButton("Clear")
        clear_selected_button.setProperty("class", "secondary_button")
        clear_selected_button.setFixedSize(120, 38)
        clear_selected_button.setLayoutDirection(Qt.RightToLeft)
        clear_selected_button.setIcon(QIcon("ui/icons/erase.svg"))
        clear_selected_button.setIconSize(QSize(20, 20))
        clear_selected_button.clicked.connect(self.clear_selected_elements)

        self.calculate_button = QPushButton("Calculate")
        self.calculate_button.setProperty("class", "primary_button")
        self.calculate_button.setFixedSize(140,38)
        self.calculate_button.setLayoutDirection(Qt.RightToLeft)
        self.calculate_button.setIcon(QIcon("ui/icons/calculation.svg"))
        self.calculate_button.setIconSize(QSize(20, 20))
        self.calculate_button.clicked.connect(self.on_calculate_button_click)

        self.restrict_button_container = QWidget()
        restrict_button_layout = QHBoxLayout(self.restrict_button_container)
        restrict_button_layout.setSpacing(15)
        restrict_button_layout.setContentsMargins(10, 10, 0, 0)
        restrict_button_layout.addStretch(1)
        restrict_button_layout.addWidget(self.step_size_label)
        restrict_button_layout.addWidget(self.step_size_edit)
        restrict_button_layout.addItem((QSpacerItem(36, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
        restrict_button_layout.addWidget(self.restrict_button)

        selected_button_container = QWidget()
        selected_button_layout = QHBoxLayout(selected_button_container)
        selected_button_layout.setSpacing(2)
        selected_button_layout.setContentsMargins(10, 10, 0, 10)
        selected_button_layout.addStretch(1)
        selected_button_layout.addWidget(clear_selected_button)
        selected_button_layout.addWidget(self.restrict_button)
        selected_button_layout.addWidget(self.calculate_button)
        
        selected_frame_layout.addWidget(self.restrict_button_container)
        selected_frame_layout.addWidget(selected_button_container)
        selected_frame_widget.setFixedSize(550, 470)
        # selected_frame_widget.setFixedHeight(500)

        top_layout.addStretch(2)
        top_layout.addWidget(selected_frame_widget)
        top_layout.addStretch(6)

        parent_layout.addLayout(top_layout)

        # Alloy information table
        bottom_layout = QVBoxLayout()

        alloy_table_layout = QHBoxLayout()
        self.alloy_table = QTableWidget(0, 16)
        self.alloy_table.setHorizontalHeaderLabels(["Alloy", "Density (g/cm³)", "δ", "γ", "ΔHₘᵢₓ (kJ/mol)", "VEC", "ΔSₘᵢₓ (kJ/mol)", "Tₘ (K)", 
                                                    "Ω", "Crystal Str.", "Model 1", "Model 2", "Model 3", "Model 4", "Model 5", "Model 6"])
        self.alloy_table.setStyleSheet("font-size: 10pt;")  # Set font size for the table
        alloy_table_layout.addItem((QSpacerItem(10, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
        alloy_table_layout.addWidget(self.alloy_table)
        alloy_table_layout.addItem((QSpacerItem(10, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))

        bottom_layout.addLayout(alloy_table_layout)

        bottom_buttons_layout = QHBoxLayout()
        bottom_buttons_layout.setSpacing(2)
        bottom_buttons_layout.addStretch(1)
        clear_alloy_button = QPushButton("Clear")
        clear_alloy_button.setFixedSize(120,38)
        clear_alloy_button.setLayoutDirection(Qt.RightToLeft)
        clear_alloy_button.setIcon(QIcon("ui/icons/clean.svg"))
        clear_alloy_button.setIconSize(QSize(23, 23))
        clear_alloy_button.clicked.connect(self.on_calculate_button_click)
        clear_alloy_button.setProperty("class", "secondary_button")
        clear_alloy_button.clicked.connect(self.clear_alloy_info)
        bottom_buttons_layout.addWidget(clear_alloy_button)

        save_button = QPushButton("Save to Excel")
        save_button.setProperty("class", "green_button")
        save_button.setFixedSize(150, 38)
        save_button.setLayoutDirection(Qt.RightToLeft)
        save_button.setIcon(QIcon("ui/icons/save.svg"))
        save_button.setIconSize(QSize(20, 20))
        save_button.clicked.connect(self.save_to_excel)
        bottom_buttons_layout.addWidget(save_button)
        bottom_buttons_layout.addItem((QSpacerItem(10, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))

        bottom_layout.addLayout(bottom_buttons_layout)
        # Status bar
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.status_bar.setMinimumHeight(30)
        self.status_bar.setMaximumHeight(30)

        # Label for status bar
        self.status_label = QLabel(self)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.status_bar.addWidget(self.status_label)

        parent_layout.addLayout(bottom_layout)

        self.setCentralWidget(main_widget)
        self.toggle_input_mode()
        self.update_window_state_buttons(self.windowState())

    def update_window_state_buttons(self, state):
        if state == Qt.WindowMaximized:
            self.normal_button.setVisible(True)
            self.maximize_button.setVisible(False)
        else:
            self.normal_button.setVisible(False)
            self.maximize_button.setVisible(True)

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            self.update_window_state_buttons(self.windowState())
        super().changeEvent(event)
        event.accept()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.old_pos:
            delta = QPoint(event.globalPosition().toPoint() - self.old_pos)
            self.window().move(self.window().x() + delta.x(), self.window().y() + delta.y())
            self.old_pos = event.globalPosition().toPoint()

            # Update visibility of maximize and normal buttons based on window state
            if self.window().windowState() == Qt.WindowMaximized:
                self.normal_button.setVisible(True)
                self.maximize_button.setVisible(False)
            else:
                self.normal_button.setVisible(False)
                self.maximize_button.setVisible(True)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.old_pos = None

    def switch_theme(self):
        current_theme = self.settings.get_theme()
        new_theme = "light" if current_theme == "dark" else "dark"
        self.settings.set_theme(new_theme)
        if new_theme == "dark":
            self.element_colors = self._read("ui/styles/element_colors_dark.json")
            for element, button in self.pTable_buttons.items():
                group = self.engine.periodic_table[element]["position"][2]
                color = self.element_colors.get(group, {"normal": "#333333", "hover": "#444444"})
                button.setStyleSheet(
                    f"""
                    QPushButton {{
                        background-color: {color["normal"]}; 
                        color: #f4f4f4; 
                        font-size: 14pt;
                        text-align: center;
                        padding: 5px;
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
            self.switch_theme_button.setIcon(QIcon("ui/icons/light.svg"))
            self.switch_theme_button.setToolTip("Light theme")
            self.info_button.setIcon(QIcon("ui/icons/information_dark.svg"))
        elif new_theme == "light":
            self.element_colors = self._read("ui/styles/element_colors_light.json")
            for element, button in self.pTable_buttons.items():
                group = self.engine.periodic_table[element]["position"][2]
                color = self.element_colors.get(group, {"normal": "#333333", "hover": "#444444"})
                button.setStyleSheet(
                    f"""
                    QPushButton {{
                        background-color: {color["normal"]}; 
                        color: {color["normal_font"]}; 
                        border-radius: 0px;
                        font-size: 14pt;
                        text-align: center;
                        padding: 5px;
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
            self.switch_theme_button.setIcon(QIcon("ui/icons/asleep.svg"))
            self.switch_theme_button.setToolTip("Dark theme")
            self.info_button.setIcon(QIcon("ui/icons/information_light.svg"))

    def show_info(self):
        # Implement your info display functionality
        pass

    def add_elements_to_table(self):
        self.table_frame.setHorizontalSpacing(3)  # Default 5
        self.table_frame.setVerticalSpacing(3)    # Default 5, border-radius: 10px
        current_theme = self.settings.get_theme()
        for element, data in self.engine.periodic_table.items():
            row, col, group = data["position"]
            color = self.element_colors.get(group, {"normal": "#333333", "hover": "#444444"})
            button = QPushButton(element)
            button.setCheckable(True)
            button.setFixedSize(40, 40)

            if current_theme == "dark":
                button.setStyleSheet(
                    f"""
                    QPushButton {{
                        background-color: {color["normal"]}; 
                        color: #f4f4f4; 
                        font-size: 14pt;
                        text-align: center;
                        padding: 5px;
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
                        font-size: 14pt;
                        text-align: center;
                        padding: 5px;
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
            button.clicked.connect(lambda _, el=element, btn=button: self.toggle_element(el, btn))
            self.table_frame.addWidget(button, row, col)
            self.pTable_buttons[element] = button

        # Add a spacer item between the second and third columns
        spacer = QSpacerItem(60, 200, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.table_frame.addItem(spacer, 0, 2, 9, 1)
    
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
                        background-color: {color["hover"]}; 
                        color: #f4f4f4;
                        border-radius: 0px;
                        font-size: 10pt;
                        padding: 2px;
                    }}"""
                )
            elif event.type() == event.Type.Leave:
                self.status_label.hide()
        return super().eventFilter(obj, event)

    def add_selected_element_to_frame(self, element):
        container = QWidget()
        layout = QGridLayout()
        container.setLayout(layout)

        label = QLabel(element)
        label.setStyleSheet("padding-left: 15px; font-weight: bold;")

        atomic_percent_edit = self.validated_line_edit("0")
        atomic_ratio_edit = self.validated_line_edit("0")
        weight_percent_edit = self.validated_line_edit("0")
        weight_edit = self.validated_line_edit("0")
        atomic_percent_end_label = QLabel("to")

        self.selected_elements[element] = {
            "atomic_percent": atomic_percent_edit,
            "atomic_ratio": atomic_ratio_edit,
            "weight_percent": weight_percent_edit,
            "weight": weight_edit,
            "to": atomic_percent_end_label
        }

        atomic_percent_edit.textChanged.connect(lambda: self.update_ar_wp_w(element))
        atomic_ratio_edit.textChanged.connect(lambda: self.update_ap_wp_w(element))
        weight_percent_edit.textChanged.connect(lambda: self.update_ap_ar_w(element))
        weight_edit.textChanged.connect(lambda: self.update_ap_ar_wp(element))
        self.total_weight_edit.textChanged.connect(lambda: self.update_weight(element))

        layout.addWidget(label, 0, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(atomic_ratio_edit, 0, 1, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(atomic_percent_edit, 0, 2, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(weight_percent_edit, 0, 3, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(weight_edit, 0, 4, Qt.AlignmentFlag.AlignCenter)

        atomic_percent_end_edit = self.validated_line_edit("35")

        layout.addWidget(atomic_percent_end_label, 0, 5, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(atomic_percent_end_edit, 0, 6, Qt.AlignmentFlag.AlignCenter)
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
                edits["atomic_ratio"].setText(f"{atomic_ratio:.6f}")
                edits["atomic_ratio"].blockSignals(False)
                weight_percent = self.atomic_to_weight_percent(element, atomic_percent)
                edits["weight_percent"].blockSignals(True)
                edits["weight_percent"].setText(f"{weight_percent:.6f}")
                edits["weight_percent"].blockSignals(False)
                weight = total_weight * (weight_percent / 100)
                edits["weight"].blockSignals(True)
                edits["weight"].setText(f"{weight:.6f}")
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
                edits["atomic_percent"].setText(f"{atomic_percent:.6f}")
                edits["atomic_percent"].blockSignals(False)
                edits["weight_percent"].blockSignals(True)
                edits["weight_percent"].setText(f"{weight_percent:.6f}")
                edits["weight_percent"].blockSignals(False)
                edits["weight"].blockSignals(True)
                edits["weight"].setText(f"{weight:.6f}")
                edits["weight"].blockSignals(False)
        elif self.wt_percent_radio.isChecked():
            max_percent = max((float(edit["atomic_percent"].text() or 0) for edit in self.selected_elements.values()), default=0)
            for element, edits in self.selected_elements.items():
                total_weight = float(self.total_weight_edit.text() or 0)
                weight_percent = float(edits["weight_percent"].text() or 0)
                atomic_percent = self.weight_to_atomic_percent(element, weight_percent)
                atomic_ratio = (atomic_percent / max_percent) if max_percent != 0 else 0
                edits["atomic_ratio"].blockSignals(True)
                edits["atomic_ratio"].setText(f"{atomic_ratio:.6f}")
                edits["atomic_ratio"].blockSignals(False)
                edits["atomic_percent"].blockSignals(True)
                edits["atomic_percent"].setText(f"{atomic_percent:.6f}")
                edits["atomic_percent"].blockSignals(False)
                weight = total_weight * (weight_percent / 100)
                edits["weight"].blockSignals(True)
                edits["weight"].setText(f"{weight:.6f}")
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
                edits["atomic_ratio"].setText(f"{atomic_ratio:.6f}")
                edits["atomic_ratio"].blockSignals(False)
                self.total_weight_edit.blockSignals(True)
                self.total_weight_edit.setText(f"{total_weight:.6f}")
                self.total_weight_edit.blockSignals(False)
                edits["weight_percent"].blockSignals(True)
                edits["weight_percent"].setText(f"{weight_percent:.6f}")
                edits["weight_percent"].blockSignals(False)
                edits["atomic_percent"].blockSignals(True)
                edits["atomic_percent"].setText(f"{atomic_percent:.6f}")
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
            self.selected_elements[element]["atomic_ratio"].setText(f"{atomic_ratio:.6f}")
            self.selected_elements[element]["atomic_ratio"].blockSignals(False)
            self.selected_elements[element]["weight_percent"].blockSignals(True)
            self.selected_elements[element]["weight_percent"].setText(f"{weight_percent:.6f}")
            self.selected_elements[element]["weight_percent"].blockSignals(False)
            weight = total_weight * (weight_percent / 100)
            self.selected_elements[element]["weight"].blockSignals(True)
            self.selected_elements[element]["weight"].setText(f"{weight:.6f}")
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
            self.selected_elements[element]["atomic_percent"].setText(f"{atomic_percent:.6f}")
            self.selected_elements[element]["atomic_percent"].blockSignals(False)
            weight_percent = self.atomic_to_weight_percent(element, atomic_percent)
            self.selected_elements[element]["weight_percent"].blockSignals(True)
            self.selected_elements[element]["weight_percent"].setText(f"{weight_percent:.6f}")
            self.selected_elements[element]["weight_percent"].blockSignals(False)
            weight = total_weight * (weight_percent / 100)
            self.selected_elements[element]["weight"].blockSignals(True)
            self.selected_elements[element]["weight"].setText(f"{weight:.6f}")
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
            self.selected_elements[element]["atomic_percent"].setText(f"{atomic_percent:.6f}")
            self.selected_elements[element]["atomic_percent"].blockSignals(False)
            atomic_ratio = (atomic_percent / max_percent) if max_percent != 0 else 0
            self.selected_elements[element]["atomic_ratio"].blockSignals(True)
            self.selected_elements[element]["atomic_ratio"].setText(f"{atomic_ratio:.6f}")
            self.selected_elements[element]["atomic_ratio"].blockSignals(False)
            weight = total_weight * (weight_percent / 100)
            self.selected_elements[element]["weight"].blockSignals(True)
            self.selected_elements[element]["weight"].setText(f"{weight:.6f}")
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
            self.selected_elements[element]["atomic_percent"].setText(f"{atomic_percent:.6f}")
            self.selected_elements[element]["atomic_percent"].blockSignals(False)
            self.selected_elements[element]["atomic_ratio"].blockSignals(True)
            self.selected_elements[element]["atomic_ratio"].setText(f"{atomic_ratio:.6f}")
            self.selected_elements[element]["atomic_ratio"].blockSignals(False)
            self.selected_elements[element]["weight_percent"].blockSignals(True)
            self.selected_elements[element]["weight_percent"].setText(f"{weight_percent:.6f}")
            self.selected_elements[element]["weight_percent"].blockSignals(False)
            self.total_weight_edit.blockSignals(True)
            self.total_weight_edit.setText(f"{total_weight:.6f}")
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
                self.selected_elements[element]["weight"].setText(f"{weight:.6f}")
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
        self.status_label.setStyleSheet("""
            QLabel {
                background-color: #ba1b23; 
                color: #ffffff; 
                border-radius: 0px;
                font-size: 10pt;
                padding: 2px;
            }""")
        self.status_label.show()
        # Clear status message (5 seconds)
        QTimer.singleShot(1300, lambda: self.status_label.hide())

    def toggle_input_mode(self):
        if self.range_radio.isChecked():
            for edits in self.selected_elements.values():
                edits["atomic_percent"].setVisible(True)
                edits["atomic_percent"].setEnabled(True)
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
                if "atomic_end" in edits:
                    edits["atomic_end"].setVisible(True)
                    edits["atomic_end"].setEnabled(True)
            self.calculate_button.setText("Explore")
            self.calculate_button.setIcon(QIcon("ui/icons/explore.svg"))
            self.restrict_button.setVisible(True)
            self.restrict_button.setEnabled(True)
            self.at_percent_radio.setVisible(True)
            self.at_percent_radio.setChecked(True)
            self.at_percent_radio.setEnabled(False)
            self.at_percent_radio.setText("Set At. % Range")
            self.at_percent_radio.setFixedWidth(432)
            self.at_ratio_radio.setVisible(False)
            self.wt_percent_radio.setVisible(False)
            self.wt_percent_radio.setChecked(False)
            self.weight_radio.setVisible(False)
            self.weight_radio.setChecked(False)
            self.total_row.setVisible(False)
            self.restrict_button_container.setVisible(True)
        elif self.single_radio.isChecked():
            for edits in self.selected_elements.values():
                edits["atomic_percent"].setVisible(True)
                edits["atomic_ratio"].setVisible(True)
                edits["weight_percent"].setVisible(True)
                self.total_weight_edit.setVisible(True)
                edits["weight"].setVisible(True)
                edits["to"].setVisible(False)
                if "atomic_end" in edits:
                    edits["atomic_end"].setVisible(False)
            self.calculate_button.setText("Calculate")
            self.calculate_button.setIcon(QIcon("ui/icons/calculation.svg"))
            self.restrict_button.setVisible(False)
            self.restrict_button.setEnabled(False)
            self.at_percent_radio.setVisible(True)
            self.at_percent_radio.setEnabled(True)
            self.at_percent_radio.setText("At. %")
            self.at_percent_radio.setFixedWidth(105)
            self.at_ratio_radio.setVisible(True)
            self.wt_percent_radio.setVisible(True)
            self.weight_radio.setVisible(True)
            self.total_row.setVisible(True)
            self.restrict_button_container.setVisible(False)
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
            if self.single_radio.isChecked():
                total_elements = len(self.selected_elements)
                if total_elements > 0:
                    equ_atomic_percent = 100 / total_elements
                    for edits in self.selected_elements.values():
                        edits["atomic_percent"].blockSignals(True)
                        edits["atomic_percent"].setText(f"{equ_atomic_percent:.2f}")
                        edits["atomic_percent"].blockSignals(False)
            elif self.range_radio.isChecked():
                for edits in self.selected_elements.values():
                    edits["atomic_percent"].setText("5")
                self.update_all_percentages()

    def clear_selected_elements(self):
        for button in self.pTable_buttons.values():
            button.setChecked(False)
        for i in reversed(range(self.selected_elements_container.count())):
            self.selected_elements_container.itemAt(i).widget().setParent(None)
        self.selected_elements.clear()
        self.total_atomic_label.setText("0.00")
        self.total_weight_percent_label.setText("0.00")

    def on_calculate_button_click(self):
        self.stop_requested = False
        if self.single_radio.isChecked():
            self.update_alloy_info()
        else:
            self.generate_alloy_compositions()

    def show_restrictions_window(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Set Restrictions")
        layout_left = QVBoxLayout()
        layout_right = QVBoxLayout()

        properties = ["density", "delta", "gamma", "enthalpy_of_mixing", "vec", "mixing_entropy", "melting_temp", "omega"]
        properties_label = ["Density (g/cm³)", "δ", "γ", "ΔHₘᵢₓ (kJ/mol)", "VEC", "ΔSₘᵢₓ (kJ/mol)", "Tₘ (K)", "Ω"]
        self.num_res_edits = {} # Numerical restrictions' edits

        for property, property_label in zip(properties, properties_label):
            checkbox = QCheckBox(property_label)
            checkbox.stateChanged.connect(lambda _, prop=property: self.toggle_restriction(prop))
            layout_left.addWidget(checkbox)
            min_edit = self.validated_line_edit("", 100, 30)
            min_edit.setProperty("class", "primary_text")
            min_edit.setPlaceholderText("Min")
            min_edit.setEnabled(False)
            max_edit = self.validated_line_edit("", 100, 30)
            max_edit.setProperty("class", "primary_text")
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
            combobox.setFixedSize(200, 30)
            combobox.addItems(dropdown_restrictions[dropdown])
            combobox.setEnabled(False)
            layout_right.addWidget(combobox)
            self.cat_res_edits[dropdown] = {
                "checkbox": checkbox,
                "dropdown": combobox}

        layout = QHBoxLayout()
        apply_button = QPushButton("Apply")
        apply_button.setFixedSize(100, 38)
        apply_button.setProperty("class", "primary_button")
        apply_button.clicked.connect(lambda: self.apply_restrictions(dialog))
        layout.addLayout(layout_left)
        layout.addItem((QSpacerItem(40, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)))
        layout.addLayout(layout_right)
        container = QVBoxLayout(dialog)
        container.addLayout(layout)
        container.addWidget(apply_button, alignment=Qt.AlignmentFlag.AlignRight)

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
                    if self.range_radio.isChecked() and "atomic_end" in edits:
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

    def load_settings(self):
        if os.path.exists("user_settings.json"):
            with open("user_settings.json", "r") as file:
                return json.load(file)
        return {}

    def save_settings(self, settings):
        with open("user_settings.json", "w") as file:
            json.dump(settings, file)
            
    def save_to_excel(self):
        settings = self.load_settings()
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

    def validated_line_edit(self, initial_value: str = "", width: int = 75, height: int = 25) -> QLineEdit:
        line_edit = QLineEdit(initial_value)
        
        validator = QDoubleValidator()
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        
        # Handling decimal points
        english_locale = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
        validator.setLocale(english_locale)
        
        line_edit.setValidator(validator)
        line_edit.setFixedSize(int(width), int(height))

        return line_edit

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("IBM Plex Sans"))
    window = MDLHEAPP()
    window.showMaximized()
    sys.exit(app.exec())