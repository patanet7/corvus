#!/usr/bin/env python3
"""Corvus paperless tool — search, read, tag documents."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_lib"))
from corvus_tool_client import main

if __name__ == "__main__":
    main("paperless")
