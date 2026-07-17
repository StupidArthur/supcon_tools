# 测试安全性说明

## 数据隔离机制

### 1. 数据库隔离

测试使用**独立的 Redis 数据库（db=15）**，与生产环境（db=0）完全隔离：

```
生产环境：db=0
  ├── data_factory:v2:current
  ├── data_factory:registry:tags
  └── ...

测试环境：db=15
  ├── test_message_bus:service:*
  ├── test_message_bus:responses
  └── ...
```

**重要**：Redis 的 `flushdb()` 只会清空**当前数据库**，不会影响其他数据库。

### 2. Key 前缀隔离

测试使用**独立的 Key 前缀（`test_message_bus`）**，与其他模块完全隔离：

```
其他模块的 Key：
  ├── data_factory:v2:current       # RealtimePublisher
  ├── data_factory:registry:tags    # ConfigServer
  └── data_factory:*                 # OPCUAServer

测试模块的 Key：
  ├── test_message_bus:service:*     # 测试专用
  ├── test_message_bus:responses     # 测试专用
  └── test_message_bus:*             # 测试专用
```

### 3. 精确清理策略

测试清理函数 `_clean_test_keys()` **只删除匹配前缀的 Key**：

```python
# 只删除以 "test_message_bus*" 开头的 Key
pattern = "test_message_bus*"
keys = redis.keys(pattern)  # 只匹配测试 Key
redis.delete(*keys)         # 只删除测试 Key
```

**不会删除**：
- `data_factory:*` - 其他模块的 Key
- `message_bus:*` - 如果生产环境也在使用（不同前缀）
- 其他任何不匹配 `test_message_bus*` 的 Key

## 安全性保证

### ✅ 不会影响生产数据

- 测试使用 db=15，生产使用 db=0
- 即使误操作，也不会影响生产数据库

### ✅ 不会影响其他模块

- 测试 Key 前缀：`test_message_bus`
- 其他模块 Key 前缀：`data_factory`
- 清理时只删除 `test_message_bus*`，不会删除 `data_factory*`

### ✅ 不会清空整个数据库

- 不使用 `flushdb()`（会清空整个数据库）
- 使用精确的 Key 匹配和删除
- 只删除测试产生的 Key

## 如果其他模块也在使用 db=15

### 场景 1：其他模块使用不同的 Key 前缀

**安全**：测试不会影响其他模块的数据

```
db=15:
  ├── test_message_bus:*     # 测试模块（会被清理）
  └── other_module:*         # 其他模块（不会被清理）
```

### 场景 2：其他模块也使用 `test_message_bus` 前缀

**有风险**：测试可能会清理其他模块的数据

**解决方案**：
1. 修改测试 Key 前缀（推荐）
   ```python
   # 在 conftest.py 中修改
   TEST_KEY_PREFIX = "my_test_message_bus"  # 使用更独特的前缀
   ```

2. 修改测试数据库（推荐）
   ```bash
   # 使用环境变量
   export TEST_REDIS_DB=14
   pytest message_bus/tests/
   ```

3. 确保其他模块使用不同的前缀

## 验证安全性

### 检查测试清理范围

运行测试前，可以手动检查：

```python
import redis

# 连接测试数据库
client = redis.Redis(db=15, decode_responses=True)

# 查看所有 Key
all_keys = client.keys("*")
print(f"所有 Key: {all_keys}")

# 查看测试 Key
test_keys = [k for k in all_keys if k.startswith("test_message_bus")]
print(f"测试 Key: {test_keys}")

# 查看其他 Key
other_keys = [k for k in all_keys if not k.startswith("test_message_bus")]
print(f"其他 Key: {other_keys}")
```

### 运行测试后验证

```python
# 运行测试后，检查其他 Key 是否还在
client = redis.Redis(db=15, decode_responses=True)
other_keys = [k for k in client.keys("*") if not k.startswith("test_message_bus")]
assert len(other_keys) == len(original_other_keys), "其他 Key 被误删了！"
```

## 最佳实践

1. **使用独立的测试数据库**
   ```bash
   export TEST_REDIS_DB=15  # 或 14, 13 等
   ```

2. **使用独特的 Key 前缀**
   ```python
   TEST_KEY_PREFIX = "test_message_bus_v1"  # 带版本号
   ```

3. **定期检查测试数据库**
   ```bash
   redis-cli -n 15 KEYS "*"
   ```

4. **生产环境禁用测试**
   - 确保生产环境不会运行测试
   - 使用环境变量控制测试数据库

## 总结

测试代码的设计已经考虑了安全性：

1. ✅ **数据库隔离**：使用独立的 db=15
2. ✅ **Key 前缀隔离**：使用 `test_message_bus` 前缀
3. ✅ **精确清理**：只删除匹配前缀的 Key
4. ✅ **不影响其他模块**：不会删除 `data_factory:*` 等 Key

**只要其他模块不使用 `test_message_bus` 前缀，就不会受到影响。**
