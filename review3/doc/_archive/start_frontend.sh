#!/bin/bash
# 启动前端开发服务器脚本（Ubuntu/Linux）

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/web_frontend"

# 检查node_modules是否存在
if [ ! -d "node_modules" ]; then
    echo "警告: node_modules不存在，正在安装依赖..."
    npm install
fi

# 启动开发服务器
npm run dev

