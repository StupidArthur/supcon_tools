# 通用画面（Dashboard）

通用运行看板，按工程存储在 `dashboard.yaml`，是展示配置，不进入 `runtimeRevision`，
编辑 dashboard 不要求重启引擎。

## 存储格式

```yaml
version: 1
pages:
  - id: main
    name: 主画面
    widgets:
      - id: level-card
        type: value
        tag: tank.level
        x: 0
        y: 0
        w: 3
        h: 2
        options:
          title: 液位
          unit: m
          decimals: 3
```

## 组件类型

| 类型 | 说明 |
|---|---|
| value | 数字卡片 |
| gauge | 仪表/百分比条（options.min/max） |
| lamp | 状态灯（options.threshold） |
| trend | 小型趋势 |
| write | 数值写入控件（原子写 pending/applied/failed） |
| alarm-list | 报警摘要 |
| text | 静态文本 |

## 编辑能力

新建/改名/删除页面；添加/删除组件；调整位置与尺寸（x/y/w/h）；
绑定 tag；编辑标题/单位/小数位；gauge 上下限；lamp 条件；保存与取消；无效 tag 标记。
布局复用 CSS Grid，不引入第二套大型画布库。

## 运行模式

- 运行模式禁止误拖动组件；
- 组件数据来自通用 `RuntimeFrame` 与 tag catalog；
- 每个组件明确显示状态：实时 / 数据过期 / 连接断开 / 位号缺失 / 写入中 / 写入失败。

## 校验

页面 ID 唯一、组件 ID 唯一、组件类型合法、尺寸为正。
写入使用临时文件 + 原子替换。

## 入口

实时模块第三个子页：组态 | 运行 | 画面。不新增应用顶层导航。
