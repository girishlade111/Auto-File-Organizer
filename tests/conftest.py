"""Pytest path setup: make the app root importable (project_detector, ...)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
