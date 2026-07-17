# 消息中间件测试文档

## 测试结构

```
tests/
├── __init__.py
├── conftest.py              # 测试配置和 Fixtures
├── test_message.py          # 消息格式测试
├── test_bus.py              # 消息总线核心功能测试
├── test_performance.py      # 性能测试
├── test_concurrency.py      # 并发测试
├── test_integration.py      # 集成测试
├── test_edge_cases.py       # 边界情况测试
├── run_tests.py             # 测试运行脚本
└── README.md                # 本文档
```

## 运行测试

### 运行所有测试

```bash
# 使用 pytest
pytest message_bus/tests/ -v

# 或使用 Python 模块
python -m pytest message_bus/tests/ -v

# 或使用测试脚本
python message_bus/tests/run_tests.py
```

### 运行特定测试文件

```bash
pytest message_bus/tests/test_bus.py -v
pytest message_bus/tests/test_performance.py -v
pytest message_bus/tests/test_concurrency.py -v
```

### 运行特定测试类

```bash
pytest message_bus/tests/test_bus.py::TestMessageBus -v
```

### 运行特定测试方法

```bash
pytest message_bus/tests/test_bus.py::TestMessageBus::test_send_and_receive_command -v
```

## 测试覆盖

### 1. 消息格式测试 (test_message.py)

- ✅ 消息创建
- ✅ 消息序列化/反序列化
- ✅ 消息往返测试
- ✅ 响应消息创建
- ✅ 错误响应创建
- ✅ 不同消息类型

### 2. 核心功能测试 (test_bus.py)

- ✅ 命令-响应模式
- ✅ 命令超时
- ✅ 异步命令
- ✅ 发布-订阅
- ✅ 服务注册与发现
- ✅ 健康检查
- ✅ 错误处理
- ✅ 多个处理器

### 3. 性能测试 (test_performance.py)

- ✅ 单条消息延迟
- ✅ 吞吐量测试
- ✅ 大负载消息
- ✅ 连接池性能对比

### 4. 并发测试 (test_concurrency.py)

- ✅ 并发请求
- ✅ 多个服务端并发
- ✅ 多个客户端并发
- ✅ 高并发场景
- ✅ 并发异步命令
- ✅ 竞态条件

### 5. 集成测试 (test_integration.py)

- ✅ 完整工作流
- ✅ 服务发现工作流
- ✅ 事件驱动工作流
- ✅ 错误恢复
- ✅ 多服务交互
- ✅ 服务生命周期

### 6. 边界情况测试 (test_edge_cases.py)

- ✅ 空负载
- ✅ None 负载
- ✅ Unicode 字符
- ✅ 嵌套负载
- ✅ 列表负载
- ✅ 缺少处理器
- ✅ 处理器返回 None
- ✅ 处理器异常
- ✅ 长服务名
- ✅ 特殊字符
- ✅ 并发同一服务
- ✅ 快速启动停止

## 测试要求

### 环境要求

1. **Redis 服务器**
   - 需要运行 Redis 服务器（默认 localhost:6379）
   - 测试使用数据库 15（测试数据库，可通过环境变量修改）

2. **Python 包**
   ```bash
   pip install pytest redis
   ```

### 测试配置

#### **数据库隔离**
- 测试使用独立的 Redis 数据库（**db=15**），不会影响生产数据（db=0）
- `flushdb()` 只会清空**当前数据库**（db=15）的数据，不会影响其他数据库
- 可以通过环境变量修改测试数据库：
  ```bash
  export TEST_REDIS_DB=14  # 使用 db=14 进行测试
  pytest message_bus/tests/
  ```

#### **Key 前缀隔离**
- 测试使用独立的 Key 前缀（`test_message_bus`）
- 清理时只删除以该前缀开头的 Key，不会影响其他 Key
- 即使其他模块也在使用 db=15，只要 Key 前缀不同，就不会受影响

#### **安全清理策略**
- 测试前后会自动清理测试相关的 Key（以 `test_message_bus` 开头）
- 不会清空整个数据库，只清理测试产生的数据
- 如果其他模块也在使用 db=15，建议：
  1. 修改 `TEST_REDIS_DB` 环境变量使用其他数据库
  2. 或者确保其他模块使用不同的 Key 前缀

## 性能基准

### 延迟基准

- **单条消息延迟**：< 10ms（本地 Redis）
- **P99 延迟**：< 20ms

### 吞吐量基准

- **吞吐量**：> 100 msg/s
- **高并发成功率**：> 95%

## 注意事项

1. **Redis 连接**：确保 Redis 服务器正在运行
2. **测试隔离**：每个测试使用独立的服务名，避免冲突
3. **清理数据**：测试前后会自动清理 Redis 数据
4. **并发安全**：确保处理器是线程安全的

## 持续集成

可以在 CI/CD 流程中运行测试：

```yaml
# GitHub Actions 示例
- name: Run tests
  run: |
    pip install pytest redis
    pytest message_bus/tests/ -v
```

## 故障排查

### Redis 连接失败

```
redis.exceptions.ConnectionError: Error connecting to Redis
```

**解决方案**：确保 Redis 服务器正在运行

### 测试超时

```
TimeoutError: Command timeout
```

**解决方案**：检查 Redis 性能，可能需要增加超时时间

### 测试数据冲突

```
AssertionError: 结果不完整
```

**解决方案**：确保测试使用不同的服务名和 Key 前缀
