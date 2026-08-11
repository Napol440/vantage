#!/usr/bin/env python3
"""vantage CLI entry point.

Run from the project root:  python run.py ...
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from vantage.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
