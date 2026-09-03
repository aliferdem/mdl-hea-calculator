# Copyright (c) Ali Fethi Erdem.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.
#
# workers/alloy_calculation.py

import tempfile
import time
import json
import os
from PySide6.QtCore import QThread, Signal

class AlloyCalculationWorker(QThread):
    update_progress = Signal(int, int, float)
    finished = Signal()
    all_results_ready = Signal(str, int)

    def __init__(self, compositions, engine, restriction_values):
        super().__init__()
        self.compositions = compositions
        self.engine = engine
        self.restriction_values = restriction_values
        self.stop_requested = False
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.json')

    def run(self):
        try:
            start_time = time.time()
            results = []
            count_meeting_criteria = 0
            total_compositions = len(self.compositions)

            for i, composition in enumerate(self.compositions):
                if self.stop_requested:
                    self.cleanup()
                    return

                alloy_name = "".join(f"{el}{self._to_subscript(str(int(percent)))}" for el, percent in composition.items())
                composition = {k: v / 100 for k, v in composition.items()}

                values, meets_criteria = self.engine.calculate(composition, self.restriction_values)
                if meets_criteria:
                    results.append((values, alloy_name))
                    count_meeting_criteria += 1

                if (i + 1) % 100 == 0 or i == total_compositions - 1:
                    elapsed_time = time.time() - start_time
                    estimated_time = elapsed_time / (i + 1) * (total_compositions - (i + 1))
                    self.update_progress.emit(i + 1, total_compositions, estimated_time)

            if self.stop_requested:
                self.cleanup()
                return

            json.dump(results, self.temp_file)
            self.temp_file.close()
            self.all_results_ready.emit(self.temp_file.name, count_meeting_criteria)
            self.finished.emit()
        finally:
            self.finished.emit()

    def cleanup(self):
        """Clean up resources if stop is requested."""
        if not self.temp_file.closed:
            self.temp_file.close()
        os.remove(self.temp_file.name)

    @staticmethod
    def _to_subscript(num_str):
        """Convert numbers to subscript format."""
        subscript_map = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
        return num_str.translate(subscript_map)