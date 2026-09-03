# Copyright (c) Metals Development Laboratory.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.
#
# workers/excel_writer.py

import xlsxwriter
from PySide6.QtCore import QThread, Signal
from utils.io_helpers import read_results_in_chunks
import json

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

        row = 1  # Start writing from the first row after the header
        with open(self.file_name, 'r') as temp_file:
            results = json.load(temp_file)  # Load all results from temp JSON

        total_rows = len(results)

        for idx, (values, alloy_name) in enumerate(results):
            row_data = [
                alloy_name,
                values["density"],
                values["melting_temp"],
                values["enthalpy_of_mixing"],
                values["mixing_entropy"],
                values["omega"],
                values["delta"],
                values["gamma"],
                values["lambda"],
                values["phi_model7"],
                values["phi_model8"],
                values["vec"],
                values["cstr"],
                values["model1"],
                values["model2"],
                values["model3"],
                values["model4"],
                values["model5"],
                values["model6"],
                values["model7"],
                values["model8"]
            ]
            for col_num, data in enumerate(row_data):
                worksheet.write(row, col_num, data)
            row += 1

            if idx % 100 == 0 or idx == total_rows - 1:
                self.progress.emit(idx + 1, total_rows)  # Update progress

        workbook.close()
        self.finished.emit(self.file_path)  # Signal completion