# Copyright (c) Metals Development Laboratory.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.
#
# components/about_dialog.py

from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTabWidget, QWidget, QScrollArea
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt

class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About HEA Calculator")
        self.setFixedSize(370, 300)
        self.setObjectName("aboutDialog")
        self.initUI()

    def initUI(self):
        tab_widget = QTabWidget(self)

        about_tab = QWidget()
        about_layout = QVBoxLayout(about_tab)
        about_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        about_layout.setContentsMargins(5, 20, 5, 5)
        about_text = QLabel('''
            <style>
                h2, h3, p { text-align: center; }
                .normal { font-weight: normal; }
            </style>

            <h2><span class="normal">MDL</span> <strong>HEA Calculator</strong></h2>
            <h3><span class="normal">Version 0.9.8</span></h3>
            <p>MDL | High-Entropy Alloy Calculator</p>
            <p>This software is developed within Metals Development<br />Laboratory (MDL) at 
                Middle East Technical University (METU).</p>
            ''')
        about_text.setStyleSheet("font-size: 9pt;")
        about_text.setOpenExternalLinks(True)
        about_layout.addWidget(about_text)
        about_layout.addStretch()

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
                    color: #4589ff; 
                    text-decoration: none;
                }
            </style>
            <table style="height: 145px; width: 239.531px;">
            <tbody>
            <tr>
            <td style="width: 330px;"><a href="https://carbondesignsystem.com/" target="_blank" rel="noopener">Carbon Design System</a>&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;</td>
            <td style="width: 46.5312px;">v10</td>
            </tr>
            <tr>
            <td style="width: 330px;"><a href="https://wiki.qt.io/Qt_for_Python" target="_blank">PySide6</a></td>
            <td style="width: 46.5312px;">6.7.3</td>
            </tr>
            <tr>
            <td style="width: 330px;"><a href="https://nuitka.net/" target="_blank">Nuitka</a></td>
            <td style="width: 46.5312px;">2.4.8</td>
            </tr>
            <tr>
            <td style="width: 330px;"><a href="https://jrsoftware.org/isinfo.php" target="_blank">Inno Setup</a></td>
            <td style="width: 46.5312px;">6.3.3</td>
            </tr>
            </tbody>
            </table>
            <p>&nbsp;</p>
            ''')
        components_text.setOpenExternalLinks(True)
        components_text.setStyleSheet("font-size: 12pt;")
        components_layout.addWidget(components_text)

        tab_widget.addTab(components_tab, "Components")

        license_tab = QWidget()
        license_layout = QVBoxLayout(license_tab)
        license_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        license_layout.setContentsMargins(0, 0, 0, 0)

        license_text = QLabel('''
            <style>
                a {
                    color: #4589ff;
                }
            </style>
            <div style="text-align: center; padding-top: 10px;">
            <p style="text-align: left;">HEA Calculator<br />Copyright &copy; 2024 Metals Development Laboratory<br />Middle East Technical University (METU), Ankara, T&uuml;rkiye</p>
            <p style="text-align: left;">HEA Calculator is an enhanced version based on the original <br />HEA Calculator, which was authored and copyrighted by <br />Doğuhan Sarıt&uuml;rk. Both versions were developed within <br />Metals Development Laboratory at Middle East Technical <br />University (METU). The original HEA Calculator remains the <br />intellectual property of Doğuhan Sarıt&uuml;rk and is licensed <br />under the GNU General Public License, Version 3 (GPLv3).</p>
            <hr />
            <p style="text-align: left;">This program, <em>HEA Calculator</em>, is free software: you can<br />redistribute it and/or modify it under the terms of the <strong>GNU<br />General Public License</strong> as published by the <strong>Free Software<br />Foundation</strong>, either version 3 of the License, or (at your<br />option) any later version.</p>
            <p style="text-align: left;">This program is distributed in the hope that it will be useful,<br />but <strong>WITHOUT ANY WARRANTY</strong>; without even the implied<br />warranty of <strong>MERCHANTABILITY</strong> or <strong>FITNESS FOR A<br />PARTICULAR PURPOSE</strong>. For more details, refer to the <strong>GNU<br />General Public License</strong>.</p>
            <p style="text-align: left;">You should have received a copy of the GNU General Public<br />License along with this program. If not, you can find it at:<br /><a href="https://www.gnu.org/licenses/" target="_new" rel="noopener">https://www.gnu.org/licenses/</a></p>
            <p style="text-align: left;">The full license text can also be found in the root directory<br />of HEA Calculator.</p>
            <hr />
            <h4 style="text-align: left;">Contact Information:</h4>
            <p style="text-align: left;">If you have any questions or concerns about the program or<br />its usage, please visit the <strong>Authors</strong> tab within the <strong>About<br />HEA Calculator</strong>&nbsp;window for further information.</p>
            <hr />
            <p style="text-align: left;">By using or modifying this software, you agree to the terms<br />and conditions outlined in the <strong>GNU General Public License</strong>.</p>
            </div>
            ''')
        license_text.setOpenExternalLinks(True)
        license_text.setStyleSheet("font-size: 9pt;")

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
                    color: #4589ff; 
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
        authors_text.setStyleSheet("font-size: 11pt;")
        authors_layout.addWidget(authors_text)

        tab_widget.addTab(authors_tab, "Authors")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.addWidget(tab_widget)
        self.setLayout(layout)