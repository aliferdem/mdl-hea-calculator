"""Legacy launcher kept for existing shortcuts and build scripts. The application lives in ``hea_calc``."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()   # spawned calculation workers (see main.py)
    from hea_calc.app import run

    sys.exit(run())
