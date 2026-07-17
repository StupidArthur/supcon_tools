# 导出模板管理模块

## 功能说明

导出模板模块用于管理“前端导出弹窗默认值”。模板与前端字段保持一一对应：

- `header_rows`
- `title_names`
- `time_format`
- `file_format`
- `sheet_name`

前端通过接口按模板名动态加载这些默认值；新增模板只需新增 YAML 文件。

## 目录结构

```text
export_templates/
├── __init__.py
├── template_manager.py
├── csv_exporter.py
├── excel_exporter.py
├── export_format_utils.py
├── templates/
│   ├── prediction.yaml
│   ├── pid_loop_tuning.yaml
│   └── ai_loop_tuning.yaml
└── README.md
```

## 模板 YAML 结构

```yaml
name: prediction
defaults:
  header_rows: 2
  title_names: "timeStamp,时间戳"
  time_format: "%Y-%m-%d %H:%M:%S"
  file_format: "csv"
  sheet_name: "控制器"
```

### 字段说明

- `name`: 模板名（通常与文件名一致）
- `defaults.header_rows`: 标题行数（`1` 或 `2`）
- `defaults.title_names`: 时间列标题；当 `header_rows=2` 时使用英文逗号分隔两段
- `defaults.time_format`: 时间格式（strftime）
- `defaults.file_format`: 默认文件格式（`csv`/`xlsx`/`xls`）
- `defaults.sheet_name`: Excel 工作表默认名称

## 接口行为

- `GET /templates/list`：扫描 `templates/*.yaml` 返回模板名
- `GET /export/format-defaults/{template_name}`：返回模板 `defaults`
- `POST /export/run`：可传 `export_format` 覆盖模板默认值

## 注意事项

1. 模板只定义导出样式默认值，导出数据列仍由运行时逻辑决定（默认取 DSL `display_args`）。
2. 导出仅包含采样周期数据（`need_sample=True`）。
3. 双行标题第二行说明从 `title_names` 解析；若未提供第二段，回退为默认“时间戳”。

