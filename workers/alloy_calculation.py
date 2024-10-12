# Copyright (c) Ali Fethi Erdem.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.
#
# workers/alloy_calculation.py

import tempfile
import time
import json
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
        start_time = time.time()
        results = []
        count_meeting_criteria = 0
        for i, composition in enumerate(self.compositions):
            if self.stop_requested:
                break

            alloy_name = "".join(f"{el}{self._to_subscript(str(int(percent)))}" for el, percent in composition.items())
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

    @staticmethod
    def _to_subscript(num_str):
        """Convert numbers to subscript format."""
        subscript_map = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
        return num_str.translate(subscript_map)