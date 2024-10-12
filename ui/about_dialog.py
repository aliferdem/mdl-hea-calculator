# Copyright (c) Ali Fethi Erdem.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.
#
# ui/about_dialog.py

from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTabWidget, QWidget, QScrollArea
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt

class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About HEAPP")
        self.setFixedSize(384, 292)
        self.initUI()

    def initUI(self):
        tab_widget = QTabWidget(self)

        about_tab = QWidget()
        about_layout = QVBoxLayout(about_tab)
        about_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        about_layout.setContentsMargins(5, 20, 5, 5)
        about_text = QLabel('''
            <style>
                a {
                    color: #007bff; 
                    text-decoration: none; /* Removes the underline */
                }
                a:hover {
                    text-decoration: underline; /* Adds underline on hover */
                }
            </style>
            <h1 style="text-align: center;">HEA Phase Predictor</h1>
            <h4 style="text-align: center;">Version 1.0.0</h4>
            <p style="text-align: center;">MDL | High-Entropy Alloy Phase Predictor</p>
            <p style="text-align: center;">This software is developed within <a href="https://metumdl.framer.website/" target="_blank">Metals Development<br />
                Laboratory (MDL)</a> at <a href="https://www.metu.edu.tr/" target="_blank">Middle East Technical University <br />
                (METU)</a>. HEAPP is a derivative of HEA Calculator.</p>
            ''')
        about_text.setStyleSheet("font-size: 9pt;")
        about_text.setOpenExternalLinks(True)
        about_layout.addWidget(about_text)

        lab_logo = QLabel()
        lab_logo_pixmap = QPixmap("ui/about_logo.svg")
        lab_logo.setPixmap(lab_logo_pixmap)
        lab_logo.setAlignment(Qt.AlignLeft)
        about_layout.addWidget(lab_logo)

        tab_widget.addTab(about_tab, "About")

        components_tab = QWidget()
        components_layout = QVBoxLayout(components_tab)
        components_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        about_layout.setSpacing(20)
        components_layout.setContentsMargins(5, 20, 5, 5)
        components_text = QLabel('''
            <style>
                a {
                    color: #007bff; 
                    text-decoration: none; /* Removes the underline */
                }
                a:hover {
                    text-decoration: underline; /* Adds underline on hover */
                }
            </style>
            <table style="height: 145px; width: 239.531px;">
            <tbody>
            <tr>
            <td style="width: 172px;"><a href="https://carbondesignsystem.com/" target="_blank" rel="noopener">Carbon Design System</a>&nbsp; &nbsp; &nbsp; &nbsp; &nbsp;&nbsp;</td>
            <td style="width: 46.5312px;">v10</td>
            </tr>
            <tr>
            <td style="width: 172px;"><a href="https://wiki.qt.io/Qt_for_Python" target="_blank">PySide6</a></td>
            <td style="width: 46.5312px;">6.7.3</td>
            </tr>
            <tr>
            <td style="width: 172px;"><a href="https://nuitka.net/" target="_blank">Nuitka</a></td>
            <td style="width: 46.5312px;">2.4.8</td>
            </tr>
            <tr>
            <td style="width: 172px;"><a href="https://jrsoftware.org/isinfo.php" target="_blank">Inno Setup</a></td>
            <td style="width: 46.5312px;">6.3.3</td>
            </tr>
            </tbody>
            </table>
            <p>&nbsp;</p>
            ''')
        components_text.setOpenExternalLinks(True)
        components_layout.addWidget(components_text)

        tab_widget.addTab(components_tab, "Components")

        license_tab = QWidget()
        license_layout = QVBoxLayout(license_tab)
        license_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        license_layout.setContentsMargins(5, 5, 5, 5)

        license_text = QLabel('''
            <style>
                a {
                    color: #007bff; 
                    text-decoration: none; /* Removes the underline */
                }
                a:hover {
                    text-decoration: underline; /* Adds underline on hover */
                }
            </style>
            <p>HEA Phase Predictor<br />Copyright &copy; 2024 Ali Fethi Erdem<br />Metals Development Laboratory<br />Middle East Technical University (METU), Ankara, T&uuml;rkiye</p>
            <p>HEA Phase Predictor is licensed under the GNU General<br />Public License Version 3.</p>
            <p>HEA Phase Predictor is a derivative of "HEA Calculator"<br />by Doğuhan Sarıt&uuml;rk, which is also licensed under the GNU<br />General Public License v3.</p>
            <p>HEA Phase Predictor is free software: you can redistribute it<br />and/or modify it under the terms of the GNU General Public<br />License as published by the Free Software Foundation, either<br />version 3 of the License, or (at your option) any later version.</p>
            <p>HEA Phase Predictor is distributed in the hope that it will be<br />useful, but WITHOUT ANY WARRANTY; without even the<br />implied warranty of MERCHANTABILITY or FITNESS FOR A<br />PARTICULAR PURPOSE. See the GNU General Public License<br />for more details.</p>
            <p>You should have received a copy of the GNU General Public<br />License along with HEA Phase Predictor. If not, see<br /><a href="https://www.gnu.org/licenses/">&lt;https://www.gnu.org/licenses/&gt;</a>.</p>
            <p><br />This software includes components from Carbon Design<br />System (v10) licensed under the Apache License, Version<br />2.0 (the "License"); you may not use this file except in<br />compliance with the License. You may obtain a copy of the<br />License at</p>
            <p><a href="http://www.apache.org/licenses/LICENSE-2.0">http://www.apache.org/licenses/LICENSE-2.0</a></p>
            <p>Unless required by applicable law or agreed to in writing,<br />software distributed under the License is distributed on an<br />"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF<br />ANY KIND, either express or implied. See the License for the<br />specific language governing permissions and limitations under<br />the License.</p>
            <p>For more information on the Carbon Design System, visit:<br /><a href="https://carbondesignsystem.com/">https://carbondesignsystem.com/</a></p>
            ''')
        license_text.setOpenExternalLinks(True)
        license_text.setStyleSheet("font-size: 8pt;")

        scroll_area = QScrollArea()
        scroll_area.setObjectName("dialog_scroll")
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        container = QWidget()
        container.setLayout(QVBoxLayout())
        container.layout().addWidget(license_text)

        scroll_area.setWidget(container)

        license_layout.addWidget(scroll_area)

        tab_widget.addTab(license_tab, "License")

        authors_tab = QWidget()
        authors_layout = QVBoxLayout(authors_tab)
        authors_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        authors_layout.setContentsMargins(5, 20, 5, 5)
        authors_text = QLabel('''
            <style>
                a {
                    color: #007bff; 
                    text-decoration: none; /* Removes the underline */
                }
                a:hover {
                    text-decoration: underline; /* Adds underline on hover */
                }
            </style>
            <p>&copy; 2024 Ali Fethi Erdem<br /><a href="mailto:erdem.alifethi@gmail.com">erdem.alifethi@gmail.com</a></p>
            <p>&copy; 2020 Doğuhan Sarıt&uuml;rk<br /><a href="mailto:dogu.sariturk@gmail.com">dogu.sariturk@gmail.com</a></p>
            ''')
        authors_text.setOpenExternalLinks(True)
        authors_layout.addWidget(authors_text)

        tab_widget.addTab(authors_tab, "Authors")

        layout = QVBoxLayout(self)
        layout.addWidget(tab_widget)
        self.setLayout(layout)