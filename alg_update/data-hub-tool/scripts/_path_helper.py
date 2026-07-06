"""把项目根目录加到 sys.path, 这样 scripts/*.py 可以:
    import _path_helper
    from common_api import AlgAPI
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
