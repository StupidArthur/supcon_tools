#!/bin/bash
# 启动后端服务器脚本（Ubuntu/Linux）

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 检查虚拟环境是否存在
if [ ! -d "venv" ]; then
    echo "错误: 虚拟环境不存在，请先创建虚拟环境"
    echo "运行: python3.12 -m venv venv"
    exit 1
fi

# 激活虚拟环境
source venv/bin/activate

# 启动服务器
python web_backend/start_server.py

