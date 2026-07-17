"""
实时数据发布模块（Redis + 消息总线）。

功能：
- 每个周期将快照推送到 Redis，更新最新值键
- 通过 Pub/Sub 发布通知，供 OPCUA 或其他订阅者消费
- 通过消息总线发布组态信息事件，供 StorageService 和 OPCUA Server 订阅
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Any, Optional
import threading
import time
from collections import deque

import redis
from redis.connection import ConnectionPool

from components.utils.logger import get_logger

# 可选导入消息总线
try:
    from components.message_bus import MessageBus, BusConfig, MessageClient
    MESSAGE_BUS_AVAILABLE = True
except ImportError:
    MESSAGE_BUS_AVAILABLE = False
    MessageBus = None
    BusConfig = None
    MessageClient = None


logger = get_logger()


@dataclass
class RealtimeConfig:
    """
    实时数据发布配置
    
    Attributes:
        redis_host: Redis 主机地址
        redis_port: Redis 端口
        redis_db: Redis 数据库编号
        redis_password: Redis 密码（可选）
        pubsub_channel: Pub/Sub 频道名称，用于通知 OPCUA/其他订阅者
        use_connection_pool: 是否使用连接池（默认 False，单线程场景可不启用）
        bus_config: 消息总线配置（如果为 None，则使用默认配置）
        enable_async_push: 是否启用异步推送（默认 True），开启后 Engine 主循环只负责入队，
                           具体 Redis 操作在后台线程中执行，减少对执行周期的影响
        max_queue_size: 异步推送队列的最大长度，用于简单限流；超过后会丢弃最旧的任务并记录告警，
                        避免极端情况下内存无限增长
    """
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    pubsub_channel: str = "data_factory"
    use_connection_pool: bool = False
    bus_config: Optional[Any] = None  # BusConfig 类型
    engine_id: str = "default"
    enable_async_push: bool = True
    max_queue_size: int = 1000


class RealtimePublisher:
    """
    实时数据发布器（Redis + 消息总线）。
    
    主要职责：
    - 更新 ``data_factory:v2:current``（Hash，位号 → JSON）
    - 发布 Pub/Sub 通知，提醒外部消费者有新数据
    - 通过消息总线发布组态信息事件
    """

    REDIS_KEY_PREFIX = "data_factory"
    # V2 架构：使用统一的多路复用大 Hash
    CURRENT_V2_KEY = f"{REDIS_KEY_PREFIX}:v2:current"
    CONFIG_EVENT = "config_update"  # 组态信息事件类型

    def __init__(self, config: RealtimeConfig):
        self.config = config
        self._redis_client: Optional[redis.Redis] = None
        self._connection_pool: Optional[ConnectionPool] = None
        self._bus: Optional[Any] = None
        self._client: Optional[Any] = None
        # 异步推送相关
        self._async_enabled: bool = bool(config.enable_async_push)
        self._push_queue: deque[Dict[str, Any]] = deque()
        self._queue_lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None
        self._worker_running: bool = False
        
        # 初始化 Redis
        self._init_redis()
        
        # 初始化消息总线（如果可用）
        if MESSAGE_BUS_AVAILABLE:
            self._init_message_bus()

        # 初始化异步推送线程
        if self._async_enabled:
            self._start_worker()
        
        logger.info(
            "RealtimePublisher initialized: redis=%s:%d/%d, channel=%s, message_bus=%s",
            config.redis_host,
            config.redis_port,
            config.redis_db,
            config.pubsub_channel,
            MESSAGE_BUS_AVAILABLE,
        )

    # ------------------------------------------------------------------#
    # 内部工具：异步推送线程
    # ------------------------------------------------------------------#

    def _start_worker(self) -> None:
        """
        启动后台工作线程，用于异步执行 Redis 推送。
        
        设计要点：
        - 单线程消费队列，避免多线程竞争 Redis 连接
        - 使用简单的 deque + 锁 实现队列，保证线程安全
        - 当队列为空时短暂 sleep，避免空转占用 CPU
        """
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return

        self._worker_running = True

        def _worker_loop() -> None:
            logger.info("RealtimePublisher async worker started")
            while self._worker_running:
                task: Optional[Dict[str, Any]] = None
                try:
                    with self._queue_lock:
                        if self._push_queue:
                            task = self._push_queue.popleft()
                    if task is None:
                        # 队列为空，稍作休眠
                        time.sleep(0.001)
                        continue

                    # 执行实际的 Redis 推送
                    self._do_push(task)
                except Exception as exc:  # noqa: BLE001
                    logger.error("RealtimePublisher async worker error: %s", exc, exc_info=True)
                    # 避免紧急失败情况下空转
                    time.sleep(0.01)

            logger.info("RealtimePublisher async worker stopped")

        self._worker_thread = threading.Thread(target=_worker_loop, daemon=True)
        self._worker_thread.start()

    def _init_redis(self) -> None:
        """初始化 Redis 连接"""
        if self.config.use_connection_pool:
            self._connection_pool = ConnectionPool(
                host=self.config.redis_host,
                port=self.config.redis_port,
                db=self.config.redis_db,
                password=self.config.redis_password,
                decode_responses=True,
                max_connections=10,
            )
            self._redis_client = redis.Redis(connection_pool=self._connection_pool)
        else:
            self._redis_client = redis.Redis(
                host=self.config.redis_host,
                port=self.config.redis_port,
                db=self.config.redis_db,
                password=self.config.redis_password,
                decode_responses=True,
            )
        # 测试连接
        self._redis_client.ping()
    
    def _init_message_bus(self) -> None:
        """初始化消息总线"""
        if not MESSAGE_BUS_AVAILABLE:
            return
        
        try:
            if self.config.bus_config:
                bus_config = self.config.bus_config
            else:
                bus_config = BusConfig(
                    redis_host=self.config.redis_host,
                    redis_port=self.config.redis_port,
                    redis_db=self.config.redis_db,
                    redis_password=self.config.redis_password,
                    key_prefix="engine"
                )
            
            self._bus = MessageBus(bus_config)
            self._client = MessageClient(self._bus, "engine")
            logger.info("消息总线初始化成功")
        except Exception as e:
            logger.warning(f"消息总线初始化失败（将回退到 Redis 方式）: {e}")
            self._bus = None
            self._client = None

    # ------------------------------------------------------------------#
    # 实际推送实现（供异步线程调用）
    # ------------------------------------------------------------------#

    def _do_push(self, push_data: Dict[str, Any]) -> None:
        """
        实际执行 Redis 推送的内部方法。
        
        Args:
            push_data: 包含 current_key、payload 和 notification 的字典
        """
        if not self._redis_client:
            logger.warning("Redis client not initialized, skip push")
            return

        current_key = push_data["current_key"]
        payload = push_data["payload"]  # 对于 V2，这可能是一个字典
        notification = push_data["notification"]

        # V2 模式：payload 是一个 Dict[tag_name, json_str]
        if isinstance(payload, dict):
            if payload:
                try:
                    # 新版 redis-py 支持 mapping 关键字参数
                    self._redis_client.hset(current_key, mapping=payload)
                except (TypeError, redis.ResponseError):
                    # 兼容旧版客户端或代理：逐条 HSET
                    pipe = self._redis_client.pipeline(transaction=False)
                    for field, val in payload.items():
                        pipe.hset(current_key, field, val)
                    pipe.execute()
        else:
            # 向后兼容：更新最新值 (V1 模式)
            self._redis_client.set(current_key, payload)

        # 发布通知
        self._redis_client.publish(self.config.pubsub_channel, notification)

    def push_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """
        推送快照到 Redis（每个周期都推送）
        
        V2 架构操作：
        1. 更新 data_factory:v2:current (Hash) 键
        2. Field 为位号全名，Value 为 {v, t, e} 的 JSON
        3. 发布通知到 Pub/Sub
        """
        try:
            # 1. 准备 V2 格式的数据 (Hash Mapping)
            sim_time = snapshot.get("sim_time", 0.0)
            engine_id = self.config.engine_id
            
            # 提取所有参数位号
            params = {
                k: v
                for k, v in snapshot.items()
                if k not in ["cycle_count", "need_sample", "time_str", "sim_time", "exec_ratio"]
            }
            
            # 构造每个位号的 Value JSON
            # 缩写字段以节省 Redis 空间：v=value, t=timestamp, e=engine_id
            v2_mapping = {
                tag: json.dumps({"v": val, "t": sim_time, "e": engine_id})
                for tag, val in params.items()
            }

            # 2. 准备通知负载
            notification_payload = json.dumps(
                {
                    "timestamp": sim_time,
                    "cycle_count": snapshot.get("cycle_count", 0),
                    "engine_id": engine_id,
                    "v": "2" # 标识这是 V2 格式通知
                }
            )

            push_task = {
                "current_key": self.CURRENT_V2_KEY,
                "payload": v2_mapping,
                "notification": notification_payload,
            }
            if self._async_enabled:
                with self._queue_lock:
                    if len(self._push_queue) >= self.config.max_queue_size:
                        self._push_queue.popleft()
                        logger.warning(
                            "RealtimePublisher queue is full, dropping oldest push task"
                        )
                    self._push_queue.append(push_task)
            else:
                self._do_push(push_task)

            cycle_count = snapshot.get("cycle_count", 0)
            if cycle_count % 1000 == 0:
                logger.info(
                    "Snapshot pushed to Redis (async=%s): cycle_count=%d, params_count=%d",
                    self._async_enabled,
                    cycle_count,
                    len(params),
                )
        except redis.ConnectionError as e:
            logger.error("Redis 连接错误，推送快照失败: %s", e, exc_info=True)
        except redis.TimeoutError as e:
            logger.error("Redis 超时错误，推送快照失败: %s", e, exc_info=True)
        except Exception as e:
            logger.error("推送快照到 Redis 失败: %s", e, exc_info=True)

    def push_config(
        self,
        cycle_time: float,
        sample_interval: Optional[float],
        stored_params: Optional[list[str]],
        instances_info: Dict[str, Any],
    ) -> None:
        """
        推送组态信息（仅通过消息总线发布事件）
        
        Args:
            cycle_time: 执行周期（秒）
            sample_interval: 采样间隔（秒），None 表示每个周期都采样
            stored_params: 需要存储的参数列表，None 表示全部存储
            instances_info: 实例信息字典
        """
        config_data = {
            "cycle_time": cycle_time,
            "sample_interval": sample_interval,
            "stored_params": stored_params,
            "instances_info": instances_info,
        }
        
        # 方式1：通过消息总线发布事件（推荐）
        if self._client:
            try:
                self._client.publish(self.CONFIG_EVENT, config_data)
                logger.debug("Config event published via message bus: cycle_time=%.3f, sample_interval=%s", 
                           cycle_time, sample_interval)
            except Exception as e:
                logger.error(f"Failed to publish config event via message bus: {e}", exc_info=True)
        
        # 注意：组态仅保留消息总线单一路径，避免多源不一致

    def close(self) -> None:
        """关闭连接"""
        try:
            # 关闭消息总线
            if self._bus:
                self._bus.close()
                logger.info("消息总线连接已关闭")
        except Exception as e:
            logger.error(f"Failed to close message bus: {e}", exc_info=True)
        
        try:
            # 关闭 Redis 连接
            if self._redis_client:
                if self.config.use_connection_pool and self._connection_pool:
                    self._connection_pool.disconnect()
                else:
                    self._redis_client.close()
                logger.info("Redis connection closed")
        except Exception as e:
            logger.error(f"Failed to close Redis connection: {e}", exc_info=True)
