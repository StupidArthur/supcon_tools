# Data Factory Next - Frontend

前端项目，使用 React + Ant Design 开发。

## 开发环境安装

### 1. 安装 Node.js

- 下载并安装 Node.js 18+：https://nodejs.org/
- 验证安装：
```bash
node --version
npm --version
```

### 2. 安装依赖

```bash
cd web_frontend
npm install
```

### 3. 启动开发服务器

```bash
npm run dev
```

前端将在 http://localhost:3000 启动

### 4. 启动后端服务器

在项目根目录下：

```bash
# 安装 Python 依赖（如果还没安装）
pip install -r requirements.txt

# 启动后端 API 服务器
uvicorn web_backend.main:app --host 0.0.0.0 --port 8000 --reload
```

后端将在 http://localhost:8000 启动

## 项目结构

```
web_frontend/
├── src/
│   ├── components/         # 通用组件
│   │   ├── Layout/         # 布局组件
│   │   └── ChartPanel.jsx  # 图表组件
│   ├── pages/              # 页面组件
│   │   ├── Home.jsx        # 首页
│   │   └── DataSimulation.jsx  # 数据模拟页面
│   ├── services/           # API 服务
│   │   └── api.js          # API 调用封装
│   ├── utils/              # 工具函数
│   │   └── constants.js    # 常量配置
│   ├── App.jsx             # 主应用组件
│   └── main.jsx            # 入口文件
├── package.json
└── vite.config.js          # Vite 配置
```

## 功能说明

### 1. 首页
- 显示项目的 README.md 内容
- 支持 Markdown 渲染

### 2. 数据模拟页面
- **左侧配置区域**：
  - 周期配置（执行周期和采样周期）
  - 总周期数（用于预估导出时间）
  - 起始时间标签
  - 输出模板选择
  - DSL 配置编辑框（预设 display_demo.yaml）
  - 模拟绘图周期数输入
  - 模拟绘图按钮

- **右侧图表区域**：
  - 显示模拟数据的曲线图
  - 显示生成时间和预估导出时间
  - 支持缩放和拖拽

## 开发说明

- 使用 Vite 作为构建工具，支持热更新
- 使用 Ant Design 作为 UI 组件库
- 使用 ECharts 绘制图表
- API 调用统一封装在 `services/api.js`
- 常量配置统一管理在 `utils/constants.js`

