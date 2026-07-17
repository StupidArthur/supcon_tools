# Ubuntu部署指南

本文档说明如何在Ubuntu系统上部署和运行data_factory_next项目（Python 3.12）。

## 系统要求

- **操作系统**: Ubuntu 20.04+ (推荐 Ubuntu 22.04 LTS)
- **Python**: 3.12
- **Node.js**: 18+ (如果使用前端)
- **系统内存**: 建议至少 2GB
- **磁盘空间**: 建议至少 1GB

## 1. 系统级依赖安装

### 1.1 Python 3.12 安装

如果系统默认Python版本不是3.12，需要安装：

```bash
# 添加deadsnakes PPA（提供多个Python版本）
sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update

# 安装Python 3.12
sudo apt install python3.12 python3.12-venv python3.12-dev

# 验证安装
python3.12 --version
```

### 1.2 系统级依赖库

以下依赖需要系统级安装（通过apt），Python包管理器无法安装：

#### 必需的系统库

```bash
# 更新包列表
sudo apt update

# 安装编译工具和基础库
sudo apt install -y \
    build-essential \
    gcc \
    g++ \
    make \
    pkg-config

# 安装Python开发头文件（已包含在python3.12-dev中）
# sudo apt install python3.12-dev  # 已在Python安装步骤中安装
```

#### PyQt6 系统依赖

PyQt6需要Qt6系统库：

```bash
# 安装Qt6和相关库
sudo apt install -y \
    qt6-base-dev \
    qt6-base-dev-tools \
    libqt6gui6 \
    libqt6widgets6 \
    libqt6core6 \
    qt6-qpa-plugins
```

#### Matplotlib 系统依赖

Matplotlib需要字体和图形库：

```bash
# 安装字体库（用于中文显示）
sudo apt install -y \
    fonts-dejavu \
    fonts-liberation \
    fontconfig

# 如果需要显示图形界面（GUI后端）
sudo apt install -y \
    libx11-dev \
    libxext-dev \
    libxrender-dev \
    libxtst6 \
    libxi6
```

#### DuckDB 系统依赖

DuckDB通常不需要额外的系统库，但如果编译安装可能需要：

```bash
# 通常不需要，但如果遇到编译问题可以安装
sudo apt install -y \
    libssl-dev \
    libffi-dev
```

#### Redis（可选，如果使用实时数据管理）

```bash
# 安装Redis服务器
sudo apt install -y redis-server

# 启动Redis服务
sudo systemctl start redis-server
sudo systemctl enable redis-server

# 验证Redis运行状态
redis-cli ping
# 应该返回: PONG
```

### 1.3 Node.js 安装（如果使用前端）

```bash
# 使用NodeSource安装Node.js 18 LTS
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# 验证安装
node --version
npm --version
```

## 2. Python依赖安装

### 2.1 创建虚拟环境（推荐）

```bash
# 在项目根目录下
cd /path/to/data_factory_next

# 创建Python 3.12虚拟环境
python3.12 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 升级pip
pip install --upgrade pip setuptools wheel
```

### 2.2 安装Python依赖

```bash
# 确保虚拟环境已激活
source venv/bin/activate

# 安装所有依赖
pip install -r requirements.txt
```

### 2.3 验证安装

```bash
# 验证关键包是否安装成功
python3.12 -c "import yaml, fastapi, uvicorn, pandas, numpy, duckdb, redis, asyncua, PyQt6, matplotlib; print('All packages imported successfully')"
```

## 3. 代码兼容性检查

### 3.1 路径兼容性

项目已使用`pathlib.Path`处理路径，跨平台兼容。检查要点：

- ✅ 所有路径操作使用`pathlib.Path`（如`Path(__file__).parent`）
- ✅ 路径拼接使用`/`操作符（`path1 / path2`）
- ✅ 文件读写使用`Path.read_text()`和`Path.write_text()`

### 3.2 Windows特定代码

项目中存在以下Windows特定内容，但**不影响Ubuntu运行**：

1. **`web_frontend/start_dev.bat`**: Windows批处理文件，Ubuntu不需要
   - Ubuntu可以使用: `npm run dev` 或创建`.sh`脚本

2. **日志模块Windows兼容性**: `utils/logger.py`中的`SafeRotatingFileHandler`
   - 代码已处理Windows文件锁定问题，在Linux上也能正常工作

### 3.3 Python 3.12兼容性

所有依赖库都支持Python 3.12：

- ✅ `pyyaml>=6.0` - 支持Python 3.12
- ✅ `fastapi>=0.111.0` - 支持Python 3.12
- ✅ `uvicorn>=0.30.0` - 支持Python 3.12
- ✅ `pandas>=2.0.0` - 支持Python 3.12
- ✅ `numpy>=1.24.0` - 支持Python 3.12
- ✅ `duckdb>=0.9.0` - 支持Python 3.12
- ✅ `redis>=5.0.0` - 支持Python 3.12
- ✅ `asyncua>=1.0.0` - 支持Python 3.12
- ✅ `PyQt6>=6.0.0` - 支持Python 3.12（需要系统Qt6库）
- ✅ `matplotlib>=3.7.0` - 支持Python 3.12

## 4. 启动服务

### 4.1 启动后端服务器

```bash
# 激活虚拟环境
source venv/bin/activate

# 方式一：使用启动脚本（推荐）
# 启动脚本会自动处理Python路径问题
python web_backend/start_server.py

# 或使用shell脚本
./start_backend.sh

# 方式二：直接使用uvicorn（需要设置PYTHONPATH）
export PYTHONPATH="${PWD}:${PYTHONPATH}"
uvicorn web_backend.main:app --host 0.0.0.0 --port 8000 --reload

# 方式三：使用Python模块方式（推荐用于生产环境）
python -m uvicorn web_backend.main:app --host 0.0.0.0 --port 8000
```

后端将在 `http://0.0.0.0:8000` 启动

### 4.2 启动前端开发服务器（可选）

```bash
cd web_frontend

# 安装前端依赖（首次运行）
npm install

# 启动开发服务器
npm run dev
```

前端将在 `http://0.0.0.0:3000` 启动

### 4.3 创建Ubuntu启动脚本（可选）

创建 `start_backend.sh`:

```bash
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
python web_backend/start_server.py
```

创建 `start_frontend.sh`:

```bash
#!/bin/bash
cd "$(dirname "$0")/web_frontend"
npm run dev
```

赋予执行权限：

```bash
chmod +x start_backend.sh start_frontend.sh
```

## 5. 常见问题排查

### 5.1 PyQt6安装失败

**问题**: `pip install PyQt6` 失败，提示缺少Qt6库

**解决**:
```bash
# 确保已安装Qt6系统库
sudo apt install -y qt6-base-dev qt6-base-dev-tools

# 重新安装PyQt6
pip install --upgrade PyQt6
```

### 5.2 Matplotlib中文显示问题

**问题**: Matplotlib图表中文显示为方块

**解决**:
```bash
# 安装中文字体
sudo apt install -y fonts-wqy-zenhei fonts-wqy-microhei

# 清除matplotlib字体缓存
rm -rf ~/.cache/matplotlib
```

### 5.3 DuckDB编译问题

**问题**: DuckDB安装时编译失败

**解决**:
```bash
# 安装编译依赖
sudo apt install -y build-essential gcc g++ make libssl-dev libffi-dev

# 使用预编译wheel
pip install --only-binary=all duckdb
```

### 5.4 Redis连接问题

**问题**: 无法连接到Redis

**解决**:
```bash
# 检查Redis服务状态
sudo systemctl status redis-server

# 如果未启动，启动Redis
sudo systemctl start redis-server

# 检查Redis配置（默认监听127.0.0.1:6379）
redis-cli ping
```

### 5.5 端口被占用

**问题**: 8000或3000端口已被占用

**解决**:
```bash
# 查找占用端口的进程
sudo lsof -i :8000
sudo lsof -i :3000

# 杀死进程（替换PID为实际进程ID）
sudo kill -9 <PID>

# 或修改配置文件使用其他端口
```

### 5.6 模块导入错误（ModuleNotFoundError: No module named 'web_backend'）

**问题**: 启动服务器时出现 `ModuleNotFoundError: No module named 'web_backend'`

**原因**: Python无法找到`web_backend`模块，因为项目根目录不在Python路径中

**解决**:
```bash
# 方式一：使用启动脚本（已修复，自动处理路径）
python web_backend/start_server.py

# 方式二：手动设置PYTHONPATH
export PYTHONPATH="${PWD}:${PYTHONPATH}"
python web_backend/start_server.py

# 方式三：使用Python模块方式
python -m uvicorn web_backend.main:app --host 0.0.0.0 --port 8000

# 方式四：从项目根目录使用uvicorn
cd /path/to/data_factory_next
export PYTHONPATH="${PWD}:${PYTHONPATH}"
uvicorn web_backend.main:app --host 0.0.0.0 --port 8000
```

**注意**: `web_backend/start_server.py`已修复，会自动将项目根目录添加到Python路径中。

## 6. 生产环境部署建议

### 6.1 使用systemd管理服务

创建 `/etc/systemd/system/data-factory-backend.service`:

```ini
[Unit]
Description=Data Factory Next Backend
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/data_factory_next
Environment="PATH=/path/to/data_factory_next/venv/bin"
ExecStart=/path/to/data_factory_next/venv/bin/python web_backend/start_server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable data-factory-backend
sudo systemctl start data-factory-backend
```

### 6.2 使用Nginx反向代理（可选）

配置Nginx反向代理前端和后端服务。

### 6.3 防火墙配置

```bash
# 允许8000端口（后端）
sudo ufw allow 8000/tcp

# 允许3000端口（前端，仅开发环境）
sudo ufw allow 3000/tcp

# 启用防火墙
sudo ufw enable
```

## 7. 验证部署

### 7.1 测试后端API

```bash
# 健康检查
curl http://localhost:8000/health

# API文档
curl http://localhost:8000/docs
```

### 7.2 测试前端

在浏览器中访问: `http://your-server-ip:3000`

## 8. 总结

### 需要独立安装的系统组件

1. **Python 3.12** - Python解释器
2. **系统编译工具** - gcc, g++, make, pkg-config
3. **Qt6库** - PyQt6的系统依赖
4. **字体库** - Matplotlib显示支持
5. **Redis** - 可选，用于实时数据管理
6. **Node.js** - 可选，用于前端开发

### 代码兼容性

- ✅ **路径处理**: 使用`pathlib.Path`，完全跨平台
- ✅ **Python版本**: 所有依赖支持Python 3.12
- ✅ **平台特定代码**: 仅有Windows批处理文件，不影响Linux运行
- ✅ **日志系统**: 已处理跨平台兼容性

### 快速安装命令汇总

```bash
# 1. 安装系统依赖
sudo apt update
sudo apt install -y \
    python3.12 python3.12-venv python3.12-dev \
    build-essential gcc g++ make pkg-config \
    qt6-base-dev qt6-base-dev-tools \
    fonts-dejavu fonts-liberation fontconfig \
    redis-server

# 2. 创建虚拟环境
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel

# 3. 安装Python依赖
pip install -r requirements.txt

# 4. 启动服务
python web_backend/start_server.py
```

---

**注意**: 如果只运行后端API服务（不使用PyQt6工具和前端），可以跳过Qt6和Node.js的安装。

