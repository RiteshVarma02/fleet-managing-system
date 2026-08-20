"""Shared pytest fixtures and sys.path bootstrap.

Adds the backend package root to ``sys.path`` so ``app.*`` is importable
regardless of the directory pytest is invoked from.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))