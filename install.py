#!/usr/bin/env python3
"""OoT Remake Mods: the installer's command line.

    python install.py            the copies of the game on this PC, and how the mod stands in each
    python install.py -h         every command

"OoT Mods.pyw" is the same as a window."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ootmods.cli import main    # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
