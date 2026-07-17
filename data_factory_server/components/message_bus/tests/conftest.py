"""
测试配置和共享 Fixtures

重要说明：
- 测试使用独立的 Redis 数据库（db=15），不会影响生产数据（db=0）
- flushdb() 只会清空当前数据库（db=15）的数据，不会影响其他数据库
- 如果其他模块也在使用 db=15，建议修改 TEST_REDIS_DB 配置
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径（确保可以导入 message_bus）
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest
import redis
import time
import os
from components.message_bus import MessageBus, BusConfig

# 测试配置：可以通过环境变量覆盖
TEST_REDIS_HOST = os.getenv("TEST_REDIS_HOST", "localhost")
TEST_REDIS_PORT = int(os.getenv("TEST_REDIS_PORT", "6379"))
TEST_REDIS_DB = int(os.getenv("TEST_REDIS_DB", "15"))  # 使用独立的测试数据库
TEST_KEY_PREFIX = "test_message_bus"  # 测试专用的 Key 前缀


def _clean_test_keys(redis_client, key_prefix):
    """
    清理测试相关的 Key（安全的方式）
    
    只删除以指定前缀开头的 Key，而不是清空整个数据库。
    这样可以确保不会影响其他模块的数据。
    
    Args:
        redis_client: Redis 客户端
        key_prefix: Key 前缀（例如 "test_message_bus"）
    
    注意：
    - 只删除以 {key_prefix}* 开头的 Key
    - 不会影响其他前缀的 Key（如 "data_factory:*"）
    - 不会影响其他数据库的数据
    """
    pattern = f"{key_prefix}*"
    try:
        keys = redis_client.keys(pattern)
        if keys:
            deleted_count = redis_client.delete(*keys)
            if deleted_count > 0:
                # 只在有删除操作时输出日志（避免测试输出过多）
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"Cleaned {deleted_count} test keys with prefix '{key_prefix}'")
    except Exception as e:
        # 清理失败不应该影响测试，只记录警告
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to clean test keys: {e}")


@pytest.fixture(scope="session")
def redis_client():
    """
    创建 Redis 客户端用于测试
    
    安全说明：
    - 使用独立的测试数据库（db=15），不会影响生产数据（db=0）
    - 使用独立的 Key 前缀（test_message_bus），不会影响其他模块的数据
    - 清理时只删除以 test_message_bus* 开头的 Key
    - 不会影响其他 Key（如 data_factory:*）
    
    如果其他模块也在使用 db=15：
    - 建议通过环境变量 TEST_REDIS_DB 修改测试数据库
    - 或者确保其他模块使用不同的 Key 前缀
    """
    client = redis.Redis(
        host=TEST_REDIS_HOST,
        port=TEST_REDIS_PORT,
        db=TEST_REDIS_DB,
        decode_responses=True
    )
    try:
        client.ping()
        
        # 安全检查：如果测试数据库中有非测试 Key，给出警告
        all_keys = client.keys("*")
        test_keys = [k for k in all_keys if k.startswith(TEST_KEY_PREFIX)]
        other_keys = [k for k in all_keys if not k.startswith(TEST_KEY_PREFIX)]
        
        if other_keys and len(other_keys) > 0:
            import warnings
            warnings.warn(
                f"测试数据库 db={TEST_REDIS_DB} 中存在非测试 Key: {other_keys[:5]}... "
                f"测试只会清理以 '{TEST_KEY_PREFIX}' 开头的 Key。"
                f"如果担心数据冲突，请通过环境变量 TEST_REDIS_DB 修改测试数据库。",
                UserWarning
            )
        
        yield client
    finally:
        # 清理测试数据（只清理测试相关的 Key，更安全）
        _clean_test_keys(client, TEST_KEY_PREFIX)
        client.close()


@pytest.fixture
def bus_config():
    """创建测试用的消息总线配置"""
    return BusConfig(
        redis_host=TEST_REDIS_HOST,
        redis_port=TEST_REDIS_PORT,
        redis_db=TEST_REDIS_DB,
        key_prefix=TEST_KEY_PREFIX,
        use_connection_pool=False,
        result_ttl=60
    )


@pytest.fixture
def bus(bus_config, redis_client):
    """
    创建测试用的消息总线
    
    安全说明：
    - 测试前后会清理测试相关的 Key（以 TEST_KEY_PREFIX="test_message_bus" 开头）
    - 不会影响其他 Key（如 "data_factory:*"）
    - 不会影响其他数据库（如 db=0）
    - 不会影响其他模块的数据
    
    清理范围：
    - 只删除以 "test_message_bus*" 开头的 Key
    - 例如：test_message_bus:service:*, test_message_bus:responses 等
    - 不会删除：data_factory:*, message_bus:*（如果存在）
    """
    # 清理测试数据（只清理测试相关的 Key）
    _clean_test_keys(redis_client, TEST_KEY_PREFIX)
    
    bus = MessageBus(bus_config)
    yield bus
    
    # 清理
    bus.close()
    _clean_test_keys(redis_client, TEST_KEY_PREFIX)


@pytest.fixture
def clean_redis(redis_client):
    """
    清理 Redis 数据（只清理测试相关的 Key）
    
    注意：只删除以 TEST_KEY_PREFIX 开头的 Key，不会清空整个数据库
    """
    _clean_test_keys(redis_client, TEST_KEY_PREFIX)
    yield
    _clean_test_keys(redis_client, TEST_KEY_PREFIX)
