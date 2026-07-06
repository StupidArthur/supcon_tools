"""
主入口文件
"""
import sys
from pathlib import Path

# 添加项目根目录到Python路径
SCRIPT_DIR = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(SCRIPT_DIR))

from PyQt6.QtWidgets import QApplication

# 支持直接运行和作为模块导入两种方式
try:
    from tool.pid_simu_ua_server.main_window import UnifiedToolWindow
except ImportError:
    # 如果绝对导入失败，尝试相对导入（当作为模块导入时）
    from .main_window import UnifiedToolWindow


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    window = UnifiedToolWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()

