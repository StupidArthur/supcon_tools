# 备注信息

> 踩过的坑、已知问题、注意事项——给下个会话的 AI 参考

## 1. 重要发现（按坑的严重程度排）

### 1.1 ❌ "覆盖" ≠ 真的覆盖

**发现时间**：2026-06-27（migrate 端到端测试时）

**现象**：
- bb_* 之前有 10000 点
- migrate 选 "覆盖已有数据"，再灌 10000 点
- 结果：bb_* 变成 **20000 点**（追加，不是覆盖）

**原因**：
- 平台的 import API 行为类似 upsert：按时间戳判重
- 不同时间戳 = 视为新数据，叠加
- 相同时间戳 = 覆盖

**影响**：
- 同时间范围重复跑会"看起来成功"但点数翻倍
- 真正的"清掉原数据再灌"做不到

**临时方案**：
- 用不重叠的时间范围（shift +N 天）
- 接受"追加"是常态

**根治**：需要 `POST /api/tag-info/delete` 之类的 API，**当前没封装**。

### 1.2 ⚠️ HTTP 200 ≠ 数据落地

**发现时间**：早期（PROGRESS.md 5.4）

**现象**：
- import_tag_value_history 返回 `is_success=True, code=00000`
- 实际数据**没进库**

**原因**：
- 平台导入是**异步处理**（多线程、批量）
- HTTP 响应只表示"请求已接收"

**解决**：
- 导入后**等 15s**
- 调 `getHistoryValueFromDB` 查回数据
- 看到 total > 0 才是真的落地

**代码位置**：`migrate.py` 的 `verify()` 函数

### 1.3 ❌ 占位 cron 不触发

**发现时间**：2026-06-27（v0.8 → v0.9 升级时）

**现象**：
- A1 第 4 段写 `0 0 0 1 1 ?`（每年 1/1 0 点）
- HTTP 200 / code=00000
- **数据 0 点落地**

**原因**：
- 平台把占位 cron 当成"未来某时才执行"
- 实际从未触发

**解决**：
- 改用活 cron：`0/5 * * * * ?`（每 5 秒）
- `migrate.py` / `convert.py` 都硬编码这个

**教训**：PROGRESS.md 6.1 之前的"占位即可"建议**已证伪**。

### 1.4 ⚠️ yyyy-MM-dd 格式静默失败

**发现时间**：2026-06-28（todo.md 8.1 验证）

**现象**：
- A 列时间用 `yyyy-MM-dd HH:mm:ss`（横杠）
- HTTP 200 / code=00000
- 0 点落地（即使数据正确）

**原因**：平台 A1 / 时间列只认 `yyyy/MM/dd HH:mm:ss`（斜杠）

**解决**：`convert.py` 强制 `-` → `/`

**教训**：**先看文档**（`tag-value-import-api.md`）就少踩这个坑。

### 1.5 ⚠️ 无效值静默丢弃

**发现时间**：2026-06-28（test_type_coerce.py）

**现象**：
- Tag Value = `True` / `False`（布尔）→ 0 点
- Tag Value = `"abc"`（无法解析的字符串）→ 0 点
- Tag Value = `"12.3x"`（部分无法解析）→ 丢一部分

**HTTP 响应**：仍然 200 / 00000

**原因**：
- 平台对无效值"尽力解析"，解析失败就丢
- 不告诉调用方哪些丢了

**解决**：
- 导入后**必须**回查（verify 环节）
- 上传前在客户端做值校验

## 2. 平台 API 行为差异

### 2.1 list_tags 的 tagName 过滤不灵

**发现时间**：2026-06-28

**现象**：
```python
api.list_tags(page=1, page_size=1, data={"tagName": "aa_float"})
# 返回 0 条
```

**原因**：平台这个 filter 不工作（实测），但用 `data={"tagName": "aa_*"}` 模糊匹配也不灵。

**解决**：
- `migrate.py` 用 `get_all_tags(page_size=2000)` 一次性拉所有 tag
- 本地建 `name_map = {tag["tagName"]: tag}` 索引
- 用 name_map 查

**注意**：100k tag 时单次拉可能慢，目前是 ~3s 接受。

### 2.2 dataType 强转规则（DOUBLE）

| 输入 | 落地值 | 备注 |
|---|---|---|
| `int` 0~99 | `0.0`~`99.0` (float) | 自动升 |
| `float` 0.5~4.5 | 同 (float) | 不变 |
| `str(int)` "0"~"99" | `0.0`~`99.0` (float) | 解析 |
| `str(float)` "0.5"~"4.5" | 同 (float) | 解析 |
| `str(sci)` "1e2" | `100.0` (float) | 解析 |
| `str(neg)` "-1.5" | `-1.5` (float) | 解析 |
| `bool` True/False | 0 点 | **静默丢弃** |
| `str(无法解析)` "abc" | 0 点 | **静默丢弃** |

完整测试见上文（探索期 `test_type_coerce.py`，已清理，结论内化于此）。

### 2.3 getHistoryValueFromDB 响应结构

**响应 `content`** 是 `dict[tagName, {pageNum, pageSize, totalPage, total, list}]`：
- **不是** MyBatis Page 标准结构（没有 records）
- 用 `total` 判断是否有数据
- `list` 是数据点列表

**`sort` 参数被忽略**：实测 `+appTime` `-appTime` `appTime` 全部返回**最新在前**。

```json
{
  "code": "00000",
  "content": {
    "aa_double": {
      "pageNum": 1, "pageSize": 100, "totalPage": 100,
      "total": 10000,
      "list": [
        {"tagName": "aa_double", "tagValue": "99.0", "tagTime": "2026-06-24 03:46:30", ...}
      ]
    }
  }
}
```

## 3. 常见错误

### 3.1 `tagName` 大小写 / 下划线错误

**症状**：找不到 tag / 创建后名字错乱

**例子**：
- 期望 `aa_ulong`，但 `aa_u_long`（多一个下划线）
- 期望 `aa_bool`，但 `aa_boolean`

**解决**：用**显式映射表**（`migrate.py` 的 `TYPE_TO_TAG` 风格），不要用 `f"{prefix}_{name.lower()}"`。

### 3.2 A1 时间列没填

**症状**：HTTP 200 但 0 点

**原因**：A1 必须是**恰好 4 段**逗号分隔，少一段都失败。

**解决**：
```python
a1 = f"{start_time},{end_time},{frequency},{cron}"
# 任何一段都不能为空（除非用 API 参数覆盖）
```

### 3.3 sheet 名 / tag 名 含特殊字符

**症状**：xlsx 保存失败 或 平台找不到 tag

**原因**：tag 名只允许 `[a-zA-Z0-9_]`，不能含 `-`、` `、`.` 等

**约定**：
- aa_* 系列：OK
- bb_* 系列：OK
- test_double_*：OK
- t_double_NN：OK
- ~~2026-06-23-test~~：NO

### 3.4 Token 截断打印被安全分类器拦截

**症状**：`print(f"token={token[:16]}...")` 会被 Bash 权限拦截

**解决**：
```python
print(f"[login] OK, token 长度 {len(token)}")
# 只显示长度, 不显示内容
```

**适用**：所有打印 token / 密码 / cookie 的地方。

## 4. PyQt6 注意点

### 4.1 QMetaObject.invokeMethod + BlockingQueuedConnection

**用法**：
```python
result = QMetaObject.invokeMethod(
    proxy, "method_name",
    Qt.ConnectionType.BlockingQueuedConnection,
    Q_ARG(type1, arg1), Q_ARG(type2, arg2),
)
```

**关键**：
- 接收方必须在**主线程**（proxy 父对象是 QMainWindow）
- 方法必须有 `@pyqtSlot(... result=type)` 装饰
- worker 线程调用 invokeMethod 会**阻塞**直到主线程执行完

**坑**：参数类型不匹配会**默默不调**方法，没报错。

### 4.2 QMessageBox 按钮颜色

**坑**：QMessageBox 自带按钮（Yes/No）**不能改颜色**，要自定义 QDialog。

**解决**：
```python
class ConfirmDialog(QDialog):
    def __init__(self, msg, default, parent):
        # 用 QPushButton, setStyleSheet 改色
        yes_btn = QPushButton("是")
        yes_btn.setStyleSheet("background-color: #4CAF50; ...")
        no_btn = QPushButton("否")
        no_btn.setStyleSheet("background-color: #F44336; ...")
```

### 4.3 setDefault(True) vs autoDefault

- `setDefault(True)`：Enter 触发这个按钮
- `setAutoDefault(True)`：按钮有焦点时 Enter 触发（更友好）

**最佳实践**：
```python
yes_btn.setDefault(default)  # default 参数控制
yes_btn.setAutoDefault(True)  # 始终 autoDefault, 让焦点切换也工作
```

## 5. PyInstaller 注意点

### 5.1 首次启动慢

**原因**：EXE 启动时解压到 `%TEMP%/_MEI*` 临时目录

**优化**：用 `--onedir` 模式代替 `--onefile`（但文件会多）

### 5.2 杀毒误报

**原因**：PyInstaller 打的 EXE 经常被报毒

**解决**：
- 提交 EXE 给杀毒厂商加白
- 买代码签名证书（贵）
- 让用户加白名单（不优雅但能跑）

### 5.3 大小 57MB

**正常**：Python 解释器 + PyQt6 + 你的代码 = 50+ MB

**优化**（如需）：
- `pip install pyqt6` 用精简版（去掉不用的 Qt 模块）
- 用 `nuitka` 替代 PyInstaller
- 拆分成多个小 EXE

## 6. 平台上的"散落物"

当前平台（10.10.58.179:31501）上的 tag 状态：

| tag 类别 | 数量 | 数据 | 备注 |
|---|---|---|---|
| aa_* | 11 | 10000 点 (部分有更多) | 原始注册，11 种 dataType |
| bb_* | 11 | 20000 点 | aa_* 改名复制的，叠加过 2 次 |
| t_double_01..02 | 2 | 0 点 | V1 时间格式验证（失败）|
| t_double_03..06 | 4 | 10 点 | V2/V3 验证 |
| t_double_07..12 | 6 | 5 点 | 类型强转测试 |
| t_double_13..20 | 8 | 10000 点 | GUI 端到端测试 (10-15 时间) |
| t_double_21..30 | 10 | 1000 点 | GUI 端到端测试 (11-01 时间) |
| t_double_31..80 | 50 | 0 点 | 没用过 |
| test_double_0..79 | 80 | 10000 点 | 早期 SGW_4418fff9f4 野导入 |
| t_double_TEST_API | 1 | 0 点 | 早期测试 |
| t_double_00 | 1 | 0 点 | 用户 curl 测试 |

**清理建议**：可以写个 delete API 工具清掉 `t_double_TEST_API` / `t_double_00` / `test_double_*`。

## 7. 命名约定

| 文件 | 命名 | 例子 |
|---|---|---|
| 测试 xlsx | `<来源>_<目的>_export.xlsx` | `t_double_21_30_export.xlsx` |
| 中间转换文件 | `<原名>_for_import.xlsx` | `t_double_test_export_for_import.xlsx` |
| 脚本 | `gen_<类型>.py` / `verify_<类型>.py` | `gen_t_double_test.py` |
| EXE | `<app>-v<version>.exe` | `hisdata-migrate-v0.9.exe` |

## 8. 演进路线

| 版本 | 状态 | 关键变化 |
|---|---|---|
| 早期 | 已废 | API 探针 (test_api.py) |
| v0.x | 已废 | 命令行导入 (import_history.py) |
| v0.9 | 当前 | 完整迁移工具 (migrate.py) + GUI + EXE |
| 未来 v1.0 | 待做 | delete API + CSV/DB 源 + Web UI |

## 9. 待清理 / 待办

- [ ] 清理平台散落 tag（t_double_TEST_API 等）
- [ ] 封装 delete API
- [ ] 加单元测试（当前靠手动验证）
- [ ] 错误日志写到文件（方便排查）
- [ ] 多 tag 进度条细分（当前只显示 1 个）
- [ ] 配置文件支持（YAML 存默认 URL/账号）
- [ ] 国际化（i18n）

## 10. 已知 bug / TODO

| 编号 | 描述 | 优先级 |
|---|---|---|
| B1 | list_tags 的 tagName filter 不灵 | 低（已用本地过滤 workaround） |
| B2 | verify 阶段只看 1 个 tag | **已修**：全量验证 |
| B3 | 阶段 5 默认"否"易误操作 | **已修**：去掉 confirm |
| B4 | 100k tag 时 get_all_tags 慢 | 低（当前 ~3s 接受） |
| B5 | PyInstaller 杀毒误报 | 已知，无法解决 |
| B6 | 重复点覆盖行为 | **待修**：缺 delete API |
| B7 | CLI 没有进度显示 | 低（GUI 有） |

## 11. 调试技巧

### 11.1 看请求 / 响应

```python
# 在 common_api.py 的 _request 里加 print
print(f"[REQ] {method} {path} body={json_body}")
print(f"[RESP] {r.status_code} body={r.text[:500]}")
```

### 11.2 单步跑某阶段

```python
from migrate import extract_tag_names, count_data_points
names = extract_tag_names("export.xlsx")
counts = count_data_points("export.xlsx")
print(dict(zip(names, counts)))
```

### 11.3 手动查 1 个 tag

```python
from common_api import AlgAPI
api = AlgAPI("http://10.10.58.179:31501")
api.login("admin", "123456", "")
result = api.get_history_value(["aa_double"], "2026-06-23", "2026-06-24", page_size=5)
print(result)
```

## 12. 联系 / 致谢

- **作者**：designed by @yuzechao
- **平台**：ibd-data-hub-web-v2.2 内部使用
- **依赖**：PyQt6, openpyxl, httpx
- **打包**：PyInstaller
