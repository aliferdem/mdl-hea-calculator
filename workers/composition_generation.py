# Copyright (c) Ali Fethi Erdem.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.
#
# Workers/alloy_calculation.py

import itertools
from PySide6.QtCore import QThread, Signal

class CompositionGenerationWorker(QThread):
    compositions_ready = Signal(list)

    def __init__(self, selected_elements, step_size):
        super().__init__()
        self.selected_elements = selected_elements
        self.step_size = step_size

    def run(self):
        compositions = []
        keys, ranges = zip(*self.selected_elements.items())
        ranges = [
            list(range(int(start), int(end) + 1, int(self.step_size)))
            for start, end in ranges
        ]
        
        for values in itertools.product(*ranges):
            composition = dict(zip(keys, values))
            if sum(composition.values()) == 100:
                compositions.append(composition)
        
        self.compositions_ready.emit(compositions)