# Copyright (c) Ali Fethi Erdem.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.
#
# Workers/excel_writer.py

import xlsxwriter
from PySide6.QtCore import QThread, Signal
from Utils.io_helpers import read_results_in_chunks

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