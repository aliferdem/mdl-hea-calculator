# Copyright (c) Metals Development Laboratory.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.
#
# workers/composition_generation.py

import itertools
from PySide6.QtCore import QThread, Signal

class CompositionGenerationWorker(QThread):
    compositions_ready = Signal(list)

    def __init__(self, selected_elements, step_size):
        super().__init__()
        self.selected_elements = selected_elements  # Dictionary of element ranges
        self.step_size = step_size  # Integer step size

    def run(self):
        compositions = []
        keys, ranges = zip(*self.selected_elements.items())

        # Convert ranges to integers and generate valid ranges for each element
        ranges = [
            [
                value for value in range(int(start), int(end) + 1, int(self.step_size))
            ]
            for start, end in ranges
        ]

        # Generate all possible combinations
        for values in itertools.product(*ranges):
            if sum(values) == 100:  # Only include combinations summing to 100
                compositions.append(dict(zip(keys, values)))

        # Emit the resulting compositions
        self.compositions_ready.emit(compositions)
