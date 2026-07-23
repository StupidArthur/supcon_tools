# 实时工程（Realtime Project）

实时工程把多个 DSL YAML 组合为一个可运行的整体，支持副本展开与全局重名校验。

## 目录格式

工程存储在用户配置目录：

```
<UserConfigDir>/DataFactory/realtime_projects/<project-id>/
  project.yaml
  sources/
    <source-id>.yaml
  alarms.yaml        # 阶段七引入，可选
  dashboard.yaml     # 阶段八引入，可选
```

`project.yaml`：

```yaml
version: 1
id: 8ba30d3a-...
name: 水箱实时工程
sources:
  - id: 3693c962-...
    name: tank.yaml
    file: sources/3693c962-....yaml
    replicas: 10
  - id: 4695bf5d-...
    name: common.yaml
    file: sources/4695bf5d-....yaml
    replicas: 1
```

- `sources/<id>.yaml` 文件名只用稳定 source-id，避免非法字符与重名。
- YAML 导入时复制内容到工程目录，不引用外部绝对路径。
- `replicas` 是组态展开规则，不是参数补丁。

## 实例展开规则

- 副本 0 保留原实例名；副本 N（N≥1）实例名加后缀 `_N`。
- DSL 内部引用（`inputs`、`expression`、`formula`、`source`）基于 AST 重写，
  只替换实例段，不替换属性名，不做字符串替换。
- 展开顺序确定：source 顺序 → replica 顺序 → DSL 程序项顺序。

## 重名校验

实例名必须全局唯一。以下情况拒绝操作并返回结构化冲突：

- 不同 YAML 原始实例重名；
- 不同 YAML 副本展开后重名；
- 单个 YAML 内部副本展开重名。

冲突时 `AddSource` / `UpdateReplicas` 返回 `{applied: false, project, validation}`，
`validation.duplicates` 含每个重名实例的来源（sourceId / replicaIndex / originalName）。

## 版本语义

`runtimeRevision` 包含：工程 ID、source 顺序、每个 source ID、replicas、
每个 source 文件字节哈希、alarms.yaml（若存在）。
不包含：显示名称、dashboard.yaml、用户趋势偏好。
工程改名不改变 revision；修改来源、副本或报警规则才改变。
