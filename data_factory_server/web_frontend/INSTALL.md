# 前端开发环境安装指南

## 前置要求

1. **Node.js 18+**
   - 下载地址：https://nodejs.org/
   - 验证安装：
     ```bash
     node --version
     npm --version
     ```

2. **Python 3.10+**（用于后端）
   - 确保已安装 Python 3.10 或更高版本

## 安装步骤

### 1. 安装前端依赖

```bash
cd web_frontend
npm install
```

### 2. 安装后端依赖（如果还没安装）

在项目根目录下：

```bash
pip install -r requirements.txt
```

## 启动开发服务器

### 方式一：使用启动脚本（推荐）

**Windows:**

1. 启动后端服务器：
   ```bash
   python web_backend/start_server.py
   ```

2. 启动前端开发服务器（新开一个终端）：
   ```bash
   cd web_frontend
   start_dev.bat
   ```

### 方式二：手动启动

1. **启动后端服务器**（在项目根目录）：
   ```bash
   uvicorn web_backend.main:app --host 0.0.0.0 --port 8000 --reload
   ```
   
   后端将在 http://localhost:8000 启动
   
   API 文档：
   - Swagger UI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc

2. **启动前端开发服务器**（在 web_frontend 目录）：
   ```bash
   npm run dev
   ```
   
   前端将在 http://localhost:3000 启动

## 访问应用

打开浏览器访问：http://localhost:3000

## 项目结构说明

```
web_frontend/
├── src/
│   ├── components/         # 通用组件
│   │   ├── Layout/         # 布局组件
│   │   │   └── Header.jsx  # 顶部导航栏
│   │   ├── ChartPanel.jsx   # 图表组件（ECharts）
│   │   └── MarkdownViewer.jsx  # Markdown 渲染组件
│   ├── pages/              # 页面组件
│   │   ├── Home.jsx        # 首页（显示 README.md）
│   │   └── DataSimulation.jsx  # 数据模拟页面
│   ├── services/           # API 服务
│   │   └── api.js          # API 调用封装
│   ├── utils/              # 工具函数
│   │   └── constants.js    # 常量配置
│   ├── App.jsx             # 主应用组件
│   └── main.jsx            # 入口文件
├── package.json            # 项目依赖配置
├── vite.config.js          # Vite 配置
└── README.md              # 项目说明
```

## 功能说明

### 1. 首页
- 显示项目的 README.md 内容
- 支持 Markdown 渲染
- 内容通过后端 API 动态加载

### 2. 数据模拟页面
- **左侧配置区域（35%）**：
  - 周期配置（执行周期和采样周期）
  - 总周期数（用于预估导出时间）
  - 起始时间标签
  - 输出模板选择（下拉框）
  - DSL 配置编辑框（预设 display_demo.yaml）
  - 模拟绘图周期数输入（建议 2000）
  - 模拟绘图按钮

- **右侧图表区域（65%）**：
  - 显示模拟数据的曲线图（ECharts）
  - 支持多条曲线同时显示
  - 支持缩放和拖拽
  - 显示统计信息：
    - 数据点数
    - 生成时间
    - 预估导出时间

## 开发说明

### API 代理配置

前端开发服务器配置了代理，所有 `/api/*` 请求会自动转发到 `http://localhost:8000`。

配置位置：`vite.config.js`

### 常量配置

所有常量统一管理在 `src/utils/constants.js`：
- API 基础地址
- 默认配置值
- 布局配置
- 表单布局配置

### API 调用

所有 API 调用统一封装在 `src/services/api.js`：
- `healthCheck()` - 健康检查
- `getDefaultConfig()` - 获取默认 DSL 配置
- `getTemplateList()` - 获取模板列表
- `simulatePreview()` - 模拟预览
- `exportData()` - 导出数据

## 常见问题

### 1. 前端无法连接后端

- 确保后端服务器已启动（http://localhost:8000）
- 检查 `vite.config.js` 中的代理配置
- 检查浏览器控制台的错误信息

### 2. CORS 错误

- 后端已配置 CORS 中间件，允许所有来源（开发环境）
- 如果仍有问题，检查后端服务器是否正常启动

### 3. 模拟预览失败

- 检查 DSL 配置格式是否正确（YAML）
- 检查后端日志查看详细错误信息
- 确保所有必要的字段都已填写

## 下一步开发

- [ ] 实现数据导出功能
- [ ] 实现实时运行页面
- [ ] 添加更多图表选项（缩放、导出图片等）
- [ ] 优化性能（大数据量处理）
- [ ] 添加错误恢复机制

