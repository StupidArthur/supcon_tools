# supcon_tools

TPT OPC UA 接入测试工具集。

## 项目定位

在没有开发环境的 Windows 机器上，通过 exe 一键完成：
- OPC UA Mock Server 部署
- TPT 数据源/位号组态
- 功能验证
- 历史测试记录管理

## 模块说明

```
supcon_tools/
├── ua_test_gui/          # 主桌面应用（Wails），最终形态为 exe
├── ua_mocker/            # OPC UA Mock Server（Python，打包为 exe）
├── ua_test_harness/      # UA 客户端功能测试执行器后端（Python）
├── tpt_api/              # TPT DataHub API 封装库（Python）
├── ua_player/            # UA 辅助工具
├── ua_tpt_loop/          # UA/TPT 循环工具
├── ua_tpt_manager/       # UA/TPT 管理工具
├── alg_update/           # 算法更新工具
├── data_factory_server/  # 数据工厂服务
└── qt5-version/          # Server 2016 1607 兼容版本
```

## 核心数据流

```
ua_test_gui (Wails/Go/React)
    ↓
启动 ua_mocker.exe → OPC UA Server
    ↓
调用 TPT REST API（/ibd-data-hub-web-v2.2/api/...）
    ↓
TPT 连接 mock server，完成组态与验证
```

## 主要技术栈

| 模块 | 技术 |
|------|------|
| ua_test_gui | Wails v2.12 + Go 1.25 + React TS + Tailwind + Shadcn |
| ua_mocker | Python 3.11 + asyncua + PyInstaller |
| ua_test_harness | Python + tpt_api + opcua-client |
| tpt_api | Python + httpx |

## 关键功能状态

### 已完成

- ua_test_gui 全面升级：架构改造、异步 StartMock、批量启停、exe 模式
- ProvisionPage 重新设计：顶部 Tabs + 数据源状态卡 + 位号管理卡 + 明细弹窗
- TPT 接口实测封装：ds-info、tag-info、String/DateTime 位号注册
- ua_mocker heartbeat 修复
- Token 自动刷新

### 待完善

- VerifyPage 设计
- DateTime 写值正确传参
- Mock 启动失败反馈、文件选择器等 UI 改进
- 最终打包部署流程

## 构建

### ua_test_gui

```bash
cd ua_test_gui
wails build
```

产物：`build/bin/ua_test_gui.exe`

### ua_mocker

```bash
cd ua_mocker
pyinstaller ua_mocker.spec
```

产物：`dist/ua_mocker.exe`

## 环境要求

- ua_test_gui：Windows 10 1809+（Server 2016 1607 请使用 qt5-version 分支）
- Go 1.25
- Node.js + npm
- Python 3.11（仅开发/打包时需要）

## 验证环境

TPT 测试环境：`http://10.10.58.153:31501`（不带 `/tpt-admin/`）
