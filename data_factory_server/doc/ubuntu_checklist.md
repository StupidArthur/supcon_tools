# Ubuntu部署检查清单

## 快速检查清单

### ✅ 系统级依赖（需要独立安装）

1. **Python 3.12**
   ```bash
   sudo apt install python3.12 python3.12-venv python3.12-dev
   ```

2. **编译工具**
   ```bash
   sudo apt install build-essential gcc g++ make pkg-config
   ```

3. **Qt6库**（PyQt6依赖）
   ```bash
   sudo apt install qt6-base-dev qt6-base-dev-tools
   ```

4. **字体库**（Matplotlib中文显示）
   ```bash
   sudo apt install fonts-dejavu fonts-liberation fontconfig
   sudo apt install fonts-wqy-zenhei fonts-wqy-microhei  # 中文字体
   ```

5. **Redis**（可选，实时数据管理）
   ```bash
   sudo apt install redis-server
   ```

6. **Node.js**（可选，前端开发）
   ```bash
   curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
   sudo apt install nodejs
   ```

### ✅ Python依赖（通过pip安装）

所有依赖都在`requirements.txt`中，支持Python 3.12：

- ✅ pyyaml>=6.0
- ✅ fastapi>=0.111.0
- ✅ uvicorn>=0.30.0
- ✅ pandas>=2.0.0
- ✅ numpy>=1.24.0
- ✅ duckdb>=0.9.0
- ✅ redis>=5.0.0
- ✅ asyncua>=1.0.0
- ✅ PyQt6>=6.0.0（需要系统Qt6库）
- ✅ matplotlib>=3.7.0（需要字体库）

### ✅ 代码兼容性检查

#### 1. 路径处理 ✅
- 所有路径操作使用`pathlib.Path`
- 路径拼接使用`/`操作符
- **完全跨平台兼容**

#### 2. Windows特定代码 ✅
- `web_frontend/start_dev.bat` - Windows批处理文件，Ubuntu不需要
- `utils/logger.py` - Windows兼容性代码，在Linux上也能正常工作
- `tools/data_plotter.py` - 已修复，支持Linux中文字体
- `tools/data_plotter_pro.py` - 已修复，支持Linux中文字体

#### 3. Python版本兼容性 ✅
- 所有依赖库都支持Python 3.12
- 代码使用标准库，无版本特定问题

#### 4. 平台特定功能 ✅
- 日志系统：已处理跨平台兼容性
- 文件操作：使用pathlib，跨平台
- 网络服务：FastAPI/uvicorn，跨平台
- GUI工具：PyQt6，跨平台（需要系统库）

### ✅ 已修复的问题

1. **字体配置** - `tools/data_plotter.py`和`tools/data_plotter_pro.py`
   - 添加了Linux中文字体支持
   - 字体列表包含Windows和Linux常用字体

2. **启动脚本** - 创建了Ubuntu启动脚本
   - `start_backend.sh` - 后端服务器启动脚本
   - `start_frontend.sh` - 前端开发服务器启动脚本

### ⚠️ 注意事项

1. **PyQt6安装**
   - 必须先安装系统Qt6库，否则pip安装会失败
   - 如果不需要GUI工具，可以不安装PyQt6

2. **Matplotlib中文显示**
   - 需要安装中文字体包
   - 安装后清除matplotlib缓存：`rm -rf ~/.cache/matplotlib`

3. **Redis服务**
   - 如果使用实时数据管理功能，需要启动Redis服务
   - `sudo systemctl start redis-server`

4. **端口占用**
   - 默认后端端口：8000
   - 默认前端端口：3000
   - 如果被占用，需要修改配置或释放端口

### 📝 部署步骤总结

```bash
# 1. 安装系统依赖
sudo apt update
sudo apt install -y \
    python3.12 python3.12-venv python3.12-dev \
    build-essential gcc g++ make pkg-config \
    qt6-base-dev qt6-base-dev-tools \
    fonts-dejavu fonts-liberation fontconfig \
    fonts-wqy-zenhei fonts-wqy-microhei \
    redis-server

# 2. 创建虚拟环境
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel

# 3. 安装Python依赖
pip install -r requirements.txt

# 4. 启动服务
chmod +x start_backend.sh start_frontend.sh
./start_backend.sh  # 后端
./start_frontend.sh  # 前端（新终端）
```

### 🔍 验证部署

```bash
# 验证Python包
python3.12 -c "import yaml, fastapi, uvicorn, pandas, numpy, duckdb, redis, asyncua, PyQt6, matplotlib; print('OK')"

# 验证后端API
curl http://localhost:8000/health

# 验证Redis
redis-cli ping
```

---

**结论**: 项目代码完全兼容Ubuntu + Python 3.12，只需要安装系统级依赖库即可正常运行。

