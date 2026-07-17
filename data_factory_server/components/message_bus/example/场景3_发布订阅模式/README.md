# 场景3：发布-订阅模式（事件驱动）

## 场景说明

演示如何使用发布-订阅模式实现事件驱动的消息传递。多个订阅者可以同时接收同一个事件。

## 运行方式

### 方式1：分别运行发布者和订阅者

1. 启动订阅者1：
```bash
python 场景3_发布订阅模式/subscriber1.py
```

2. 启动订阅者2：
```bash
python 场景3_发布订阅模式/subscriber2.py
```

3. 启动发布者：
```bash
python 场景3_发布订阅模式/publisher.py
```

### 方式2：运行完整示例

```bash
python 场景3_发布订阅模式/完整示例.py
```

## 功能说明

- **发布者**：发布配置更新事件
- **订阅者1**：订阅配置更新事件，执行配置重载
- **订阅者2**：订阅配置更新事件，执行缓存清理

## 预期输出

发布者输出：
```
发布事件: config_updated, 数据: {'config_path': '/path/to/config.yaml'}
发布事件: config_updated, 数据: {'config_path': '/path/to/config2.yaml'}
```

订阅者1输出：
```
[订阅者1] 已订阅事件: config_updated
[订阅者1] 收到事件: config_updated
[订阅者1] 执行配置重载: /path/to/config.yaml
[订阅者1] 收到事件: config_updated
[订阅者1] 执行配置重载: /path/to/config2.yaml
```

订阅者2输出：
```
[订阅者2] 已订阅事件: config_updated
[订阅者2] 收到事件: config_updated
[订阅者2] 执行缓存清理: /path/to/config.yaml
[订阅者2] 收到事件: config_updated
[订阅者2] 执行缓存清理: /path/to/config2.yaml
```
