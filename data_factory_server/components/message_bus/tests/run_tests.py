"""
运行所有测试

使用方式：
    python -m pytest message_bus/tests/
    或者
    python message_bus/tests/run_tests.py
"""
import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest

if __name__ == "__main__":
    # 获取测试目录
    test_dir = Path(__file__).parent
    
    # 运行所有测试
    pytest.main([
        str(test_dir),
        "-v",  # 详细输出
        "-s",  # 显示 print 输出（性能测试需要）
        "--tb=short",  # 简短的错误追踪
    ])
