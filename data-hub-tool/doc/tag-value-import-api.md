# TagValueController 导入位号历史值 API 调用说明

## 1. importTagValueHistory — Excel/ZIP 导入位号历史值

### 基本信息

| 项目 | 说明 |
|------|------|
| URL | `POST /api/tag-value/importTagValueHistory` |
| Content-Type | `multipart/form-data` |
| 认证 | 需要登录认证 |

### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 说明 |
|--------|------|------|------|------|
| file | MultipartFile | form-data | 是 | 上传的文件，支持 `.xls`、`.xlsx`、`.zip`（ZIP 内含 Excel） |
| dsId | Long | form-data | 否 | 关系型数据源ID。若提供且非0，数据将直接写入该关系型数据库；否则写入默认时序库 |
| startTime | String | form-data | 否 | 导入数据的起始时间过滤 |
| endTime | String | form-data | 否 | 导入数据的结束时间过滤 |
| frequency | String | form-data | 否 | 采样频率 |
| corn | String | form-data | 否 | Cron 表达式，用于定时导入任务 |

### 文件限制

- 文件大小上限：**1GB**（1024MB），超过此限制需通过"数仓-文件管理"上传
- 支持格式：`.zip`、`.xls`、`.xlsx`，其他格式返回错误

### Excel 文件格式

#### Sheet 结构

每个 Sheet 页代表一组位号的历史数据，支持多 Sheet 页。每个 Sheet 的格式如下：

**第 1 行（表头行）**：
- **A1 单元格**（第0列）：可选，填写元信息，格式为逗号分隔的 4 个字段：`startTime,endTime,frequency,corn`
  - 若提供且 API 参数未传，则使用此处的值
  - 若 A1 为空或逗号分隔后恰好 4 段，则作为元信息解析
- **B1 及之后**（第1列起）：**位号名称（tagName）**，每个列对应一个位号

**第 2 行**：跳过不处理（预留行）

**第 3 行起**：数据行

#### 列定义

| 列 | 位置 | 说明 |
|----|------|------|
| 时间列 | 第 0 列（A列） | 数据采集时间，支持两种格式：`yyyy/MM/dd HH:mm:ss` 或 `yyyy/MM/dd HH:mm:ss.SSS` |
| 位号值列 | 第 1 列起（B、C、D...） | 对应表头中的位号名称，值为该位号在此时点的值 |

#### 质量码

- 所有导入数据的质量码固定为 **192**（良好质量），由 `TagValueQualityHandler.COMMON_QUALITY` 指定

#### 数据类型

- 不存在的位号会自动创建，默认数据类型为 **DOUBLE**
- 已存在的位号使用其原有数据类型

#### 位号分组

- 每个文件会自动创建或复用一个名为 `{文件名}_MOCK` 的位号分组
- 文件中所有位号（包括自动创建的）都关联到该分组

#### Excel 示例

| | A | B | C | D |
|---|---|---|---|---|
| **1** | 2026/01/01 00:00:00,2026/12/31 23:59:59,60,0 0/5 * * * ? | tag_temperature | tag_pressure | tag_flow |
| **2** | *(跳过)* | | | |
| **3** | 2026/06/11 08:00:00 | 25.3 | 101.5 | 120.8 |
| **4** | 2026/06/11 08:01:00 | 25.5 | 101.3 | 121.2 |
| **5** | 2026/06/11 08:02:00 | 25.8 | 101.6 | 120.5 |
| **6** | 2026/06/11 08:03:00.500 | 26.1 | 101.4 | 119.8 |

> **说明**：A1 中的 `2026/01/01 00:00:00,2026/12/31 23:59:59,60,0 0/5 * * * ?` 分别表示 startTime、endTime、frequency、corn，仅在 API 参数未传时生效。

#### ZIP 文件格式

ZIP 包内可包含多个 `.xls` 或 `.xlsx` 文件，每个文件独立解析，多线程并发处理。ZIP 文件名使用 GBK 编码解压。

```
data.zip
├── factory_line1.xlsx      # 产线1的历史数据
├── factory_line2.xlsx      # 产线2的历史数据
└── factory_line3.xlsx      # 产线3的历史数据
```

### 响应体

```json
{
  "code": 200,
  "msg": "操作成功",
  "data": null
}
```

导入完成后，系统会通过消息中心向当前用户推送导入结果通知，包含每个文件的导入成功/失败页数及异常信息。

### 处理流程

```
1. 文件校验（大小 ≤ 1GB、格式为 zip/xls/xlsx）
2. 文件转换：
   - ZIP 文件 → 解压为多个 Excel 文件流
   - 单个 Excel → 直接作为流处理
3. 多线程并发解析（线程数 = CPU 核心数）
4. 每个 Excel 使用 EasyExcel 逐行解析，通过 Flux 流式管道分批处理
5. 数据写入：
   - 指定 dsId → 获取关系型数据库连接，通过 MyBatis Mapper 批量写入（每批 500 条），手动事务提交/回滚
   - 未指定 dsId → 通过 TagValueWriteService 写入默认时序库（IoTDB/TDengine/vxbase 等）
6. 全部文件解析完成后，通过消息中心推送导入结果
```

### 调用示例

```bash
# 导入单个 Excel 文件到默认时序库
curl -X POST "http://host:31501/ibd-data-hub-web-v2.2/api/tag-value/importTagValueHistory" \
  -H "Authorization: Bearer <token>" \
  -F "file=@history_data.xlsx"

# 导入 ZIP 包到指定关系型数据源
curl -X POST "http://host:31501/ibd-data-hub-web-v2.2/api/tag-value/importTagValueHistory" \
  -H "Authorization: Bearer <token>" \
  -F "file=@data.zip" \
  -F "dsId=123" \
  -F "startTime=2026-01-01 00:00:00" \
  -F "endTime=2026-06-01 00:00:00"
```

---

## 2. importCSVTagValueHistory — CSV 导入位号历史值（已废弃）

### 基本信息

| 项目 | 说明 |
|------|------|
| URL | `POST /api/tag-value/importCSVTagValueHistory` |
| Content-Type | `multipart/form-data` |
| 认证 | 需要登录认证 |
| 状态 | **@Deprecated**，已废弃 |

### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 说明 |
|--------|------|------|------|------|
| file | MultipartFile | form-data | 是 | 上传的 CSV 文件，UTF-8 编码 |

### CSV 文件格式要求

- **首行**为表头（列名），第一列为 `time`，其余列为位号名称（tagName）
- **时间格式**：`yyyy/M/d H:mm:ss`（如 `2026/1/15 8:30:00`）
- **质量码**：固定为 192（良好质量）
- 每满 **5000** 行批量写入一次数据库

#### CSV 示例

```csv
time,tag1,tag2,tag3
2026/1/15 8:00:00,100.5,200.3,300.1
2026/1/15 8:01:00,101.2,201.5,301.8
2026/1/15 8:02:00,102.0,202.1,302.5
```

### 响应体

```json
{
  "code": 200,
  "msg": "操作成功",
  "data": null
}
```

### 处理流程

```
1. 读取 CSV 文件（UTF-8 编码，64KB 缓冲区）
2. 使用 Apache Commons CSV 解析，首行作为表头
3. 逐行解析，每行转为 Map<列名, 值>
4. 每 5000 行批量处理：
   - 提取 time 列作为 appTime/tagTime
   - 其余列每列生成一个 TagValueDTO（tagName=列名, tagValue=值, quality=192）
5. 调用 tagValueService.importTagValue() 写入
   - 不存在的位号会自动创建 TagInfo 并关联到默认分组
   - 根据位号数据类型设置 dataType
6. 写入默认时序库
```

### 调用示例

```bash
curl -X POST "http://host:31501/ibd-data-hub-web-v2.2/api/tag-value/importCSVTagValueHistory" \
  -H "Authorization: Bearer <token>" \
  -F "file=@history.csv"
```

---

## 3. importTagValue — JSON 批量导入位号历史值

### 基本信息

| 项目 | 说明 |
|------|------|
| URL | `POST /api/tag-value/importTagValue` |
| Content-Type | `application/json` |
| 认证 | 需要登录认证 |

### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 说明 |
|--------|------|------|------|------|
| data | List\<TagValueDTO\> | body | 是 | 位号值列表，最大 **10000** 条 |

### TagValueDTO 结构

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| tagName | String | 是 | 位号名称 |
| tagValue | Object | 是 | 位号值 |
| quality | Long | 否 | 质量码 |
| tagTime | LocalDateTime | 否 | 位号时间 |
| appTime | LocalDateTime | 否 | 应用时间 |
| dataType | Integer | 否 | 数据类型编码 |

### 请求体示例

```json
{
  "data": [
    {
      "tagName": "tag1",
      "tagValue": 100.5,
      "quality": 192,
      "tagTime": "2026-06-11T10:00:00",
      "appTime": "2026-06-11T10:00:00"
    },
    {
      "tagName": "tag2",
      "tagValue": 200.3,
      "quality": 192,
      "tagTime": "2026-06-11T10:00:00",
      "appTime": "2026-06-11T10:00:00"
    }
  ]
}
```

### 响应体

```json
{
  "code": 200,
  "msg": "操作成功",
  "data": {
    "tagName1": ["error message"],
    "tagName2": ["error message"]
  }
}
```

`data` 中仅包含导入失败的位号及其错误信息，成功导入的位号不会出现在返回结果中。

### 处理流程

```
1. 校验数据量 ≤ 10000
2. 为每条数据生成雪花 ID，设置租户ID
3. 按 tagName 分组
4. 查询 TagInfo 表，检查位号是否存在
5. 不存在的位号 → 自动创建 TagInfo + 关联默认分组 + 同步到向量库
6. 根据位号数据类型设置 dataType
7. 过滤掉 tagValue 为 null 的记录
8. 通过 TagValueWriteService 写入默认时序库
```

### 调用示例

```bash
curl -X POST "http://host:31501/ibd-data-hub-web-v2.2/api/tag-value/importTagValue" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "data": [
      {"tagName": "tag1", "tagValue": 100.5, "quality": 192, "tagTime": "2026-06-11T10:00:00", "appTime": "2026-06-11T10:00:00"},
      {"tagName": "tag2", "tagValue": 200.3, "quality": 192, "tagTime": "2026-06-11T10:00:00", "appTime": "2026-06-11T10:00:00"}
    ]
  }'
```

---

## 三个 API 对比

| 对比项 | importTagValueHistory | importCSVTagValueHistory | importTagValue |
|--------|----------------------|--------------------------|----------------|
| 状态 | 正常使用 | **已废弃** | 正常使用 |
| 输入格式 | Excel / ZIP(含Excel) | CSV | JSON |
| 数据量限制 | 1GB | 无限制（流式处理） | 10000 条 |
| 写入目标 | 时序库 或 关系型数据库 | 时序库 | 时序库 |
| 位号自动创建 | 通过 Excel 监听器处理 | 是（自动创建不存在的位号） | 是（自动创建不存在的位号） |
| 质量码 | Excel 中指定 | 固定 192 | 请求中指定 |
| 多线程 | 是（CPU核心数线程池） | 否（单线程） | 否（单线程） |
| 结果通知 | 消息中心推送 | 无 | 返回失败位号列表 |
| 时间格式 | Excel 日期格式 | `yyyy/M/d H:mm:ss` | ISO `yyyy-MM-ddTHH:mm:ss` |
