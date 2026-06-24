"""Backward-compatible import path for the digitizer core.

The implementation now lives in ``src/aidigitizer/core.py``. This shim keeps old
scripts that import ``digitizer_core.AdvancedDigitizerCore`` working.
"""

from pathlib import Path
import sys

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aidigitizer.core import AdvancedDigitizerCore

__all__ = ["AdvancedDigitizerCore"]


if __name__ == "__main__":
    core = AdvancedDigitizerCore()
    print("Core algorithm initialized.")
