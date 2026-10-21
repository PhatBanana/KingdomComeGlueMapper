#!/usr/bin/env python3
"""Run the standalone GlueMapper -> KCDMP map patch project."""
import sys

if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 or newer is required. No pip packages are needed.")

from kcdmp_bridge.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
