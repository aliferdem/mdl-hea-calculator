"""HEA Calculator — launch the PySide6 application."""

import multiprocessing
import sys

if __name__ == "__main__":
    # Calculation workers are spawned processes (hea_calc/core/jobs.py).  They import this file as
    # ``__mp_main__``, so nothing beyond the guard may start the GUI; freeze_support() lets a frozen
    # build re-enter as a worker.
    multiprocessing.freeze_support()
    from hea_calc.app import run

    sys.exit(run())