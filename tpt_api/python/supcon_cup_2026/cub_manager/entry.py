#!/usr/bin/env python3
"""PyInstaller 打包入口。"""

import os
import sys

if not hasattr(sys, "_MEIPASS"):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from supcon_cup_2026.cub_manager.main import main

if __name__ == "__main__":
    main()
