# data-hub-tool

数据中枢平台 `ibd-data-hub-web-v2.2` 的**位号历史值迁移工具**（hisdata-migrate v0.91）。

核心场景：从一个环境导出位号的历史数据 xlsx，转换格式后在另一个环境导入并验证。

> 详细文档见 [`doc/`](doc/)，入口 [`doc/README.md`](doc/README.md)。

## 快速上手

### GUI（PyQt6）

```bash
pip install -r requirements.txt
# 或手动: pip install PyQt6 openpyxl httpx 'numpy<2.0'
python migrate_gui.py
```

弹窗式：选源 xlsx → 填目标 URL / 用户 / 密码 → 点"开始迁移"（6 阶段自动跑）。

GUI 布局（v0.91）：输入卡 → 按钮 → 横向 stepper → **单一 OUTPUT textarea**（阶段日志、表格、日志都在这一处滚动回看）→ 状态行 → footer。默认窗口 1180 × 900。

### 命令行

```bash
python migrate.py --xlsx export.xlsx \
                  --target-url http://target-env:31501 \
                  --target-user admin \
                  --target-password yyy
```

### 打包 EXE

```bash
# 1. 装锁定依赖 (numpy 必须 <2.0, 否则老机器跑不起来 X86_V2 指令集)
pip install -r requirements.txt

# 2. 用 spec 打包
pyinstaller hisdata-migrate-v0.91.spec --clean

# 产物：dist/hisdata-migrate-v0.91.exe (~ 57 MB)
```

跑起来后 `logs/YYYY-MM-DD.log` 会自动落盘（exe 同级目录），出问题把这整个文件夹打包回来。

## 目录结构

```
data-hub-tool/
├── migrate.py / migrate_gui.py     # 迁移业务逻辑 + PyQt6 GUI（单 OUTPUT textarea）
├── common_api.py                   # 平台 HTTP API 客户端 (AlgAPI, 默认 timeout 60s)
├── convert.py / xlsx_io.py         # 格式转换 + xlsx 读写
├── log_config.py                   # 生产日志配置（exe 同级 logs/）
├── requirements.txt                # 锁定依赖（含 numpy<2.0）
├── hisdata-migrate-v0.91.spec      # PyInstaller 打包配方
├── scripts/                        # 辅助工具 (转换 / 测试数据生成)
├── doc/                            # 文档 (需求 / 设计 / 数据格式 / 备注 / 接口)
└── data/                           # inputs=真实输入, samples=标准样例
```
