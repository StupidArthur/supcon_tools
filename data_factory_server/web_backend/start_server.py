"""
启动 FastAPI 服务器

使用函数参数方式传参，符合项目规范
"""

import sys
from pathlib import Path
import uvicorn

# 将项目根目录添加到Python路径，确保可以导入web_backend模块
_project_root = Path(__file__).parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def start_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
):
    """
    启动 FastAPI 服务器
    
    Args:
        host: 服务器地址，默认 0.0.0.0
        port: 服务器端口，默认 8000
        reload: 是否启用自动重载，默认 False（避免重复启动基础服务）
    """
    uvicorn.run(
        "web_backend.main:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    start_server()

