"""Run the jevbrief benchmark. Same as `jevbrief bench bench/tasks.json`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jevbrief.cli import main

if __name__ == "__main__":
    sys.exit(main(["bench", str(Path(__file__).with_name("tasks.json")), *sys.argv[1:]]))
