#!/usr/bin/env python3
"""Launcher for KeyTrends -- works from any working directory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from keytrends.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
