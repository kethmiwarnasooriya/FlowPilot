"""Entry point: `python -m flowpilot <command>`. See `python -m flowpilot --help`."""

import sys

from flowpilot.cli import main

if __name__ == "__main__":
    sys.exit(main())
