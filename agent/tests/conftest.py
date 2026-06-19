"""Test bootstrap.

Ensures the agent project directory (the parent of this ``tests`` package) is
on ``sys.path`` so ``import agentcore`` works regardless of how the suite is
launched (``python -m unittest`` from anywhere, or ``pytest``).
"""

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
