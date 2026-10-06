#!/usr/bin/env python3
"""archiGuard - architecture gates for GitHub Spec Kit (launcher for the engine in archiguard_core/).

    python .specify/extensions/archiguard/scripts/python/archiguard.py <command> [options]

Standard library only, Python 3.9+. Exit codes: 0 pass, 1 repairable violations,
2 cannot evaluate (fail-closed), 3 escalated.
"""

import sys
from pathlib import Path

if sys.version_info < (3, 9):
    sys.stderr.write("archiGuard: ERROR: Python 3.9 or newer is required\n")
    sys.exit(2)

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from archiguard_core.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
