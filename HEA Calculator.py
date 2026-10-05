"""Legacy launcher kept for existing shortcuts and build scripts. The application lives in ``hea_calc``."""

import sys

from hea_calc.app import run

if __name__ == "__main__":
    sys.exit(run())
