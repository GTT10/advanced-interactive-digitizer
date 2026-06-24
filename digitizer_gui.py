"""Backward-compatible GUI entry point.

Prefer ``aidigitizer`` after installing the package, but ``python digitizer_gui.py``
still works for quick local use.
"""

from pathlib import Path
import sys

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aidigitizer.gui import DigitizerUI, main

__all__ = ["DigitizerUI", "main"]


if __name__ == "__main__":
    main()
