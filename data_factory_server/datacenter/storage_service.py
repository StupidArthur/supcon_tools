"""
独立存储服务

从消息总线订阅组态信息事件，从 Redis 获取数据，存储到 DuckDB，并提供查询接口。
独立进程运行，与 Engine 完全解耦。
"""

from __future__ import annotations

import json
import time
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

import redis
import duckdb

from controller.clock import Clock, ClockConfig, ClockMode
from components.utils.logger import get_logger

# 可选导入消息总线
try:
    from components.message_bus import MessageBus, BusConfig, ServiceRegistry
    MESSAGE_BUS_AVAILABLE = True
except ImportError:
    MESSAGE_BUS_AVAILABLE = False
    MessageBus = None
    BusConfig = None
    ServiceRegistry = None


logger = get_logger()

# 常量定义
BATCH_INSERT_SIZE = 500  # 批量插入缓冲区大小（增加到500，减少刷新频率）
CURRENT_KEY = "data_factory:v2:current"  # V2 当前数据键 (Hash)
CONFIG_EVENT = "config_update"  # 组态信息事件类型


@dataclass
class StorageServiceConfig:
    """
    存储服务配置
    
    Attributes:
        redis_host: Redis 主机地址
        redis_port: Redis 端口
        redis_db: Redis 数据库编号
        redis_password: Redis 密码（可选）
        db_path: DuckDB 文件路径
        bus_config: 消息总线配置（如果为 None，则使用默认配置）
        use_message_bus: 是否使用消息总线订阅组态信息（默认 True）
        
    注意：
        - 循环频率由 Clock 的 cycle_time 控制，不再使用固定的 update_cycle
        - 只在 need_sample=True 时读取 Redis 并存储数据，减少不必要的读取
        - 如果 sample_interval=10s，则每 10s 才读取一次 Redis（而不是每 100ms）
    """
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    # 默认将历史数据库写入项目同级目录下的 storage 目录，避免提交代码时把数据库文件也提交上去
    db_path: str = str(Path(__file__).parent.parent.parent / "storage" / "storage_service.duckdb")
    bus_config: Optional[Any] = None  # BusConfig 类型
    use_message_bus: bool = True  # 是否使用消息总线


class StorageService:
    """
    独立存储服务（只负责数据写入）
    
    功能：
    - 从消息总线订阅组态信息事件
    - 使用 Clock 模块控制采样周期
    - 从 Redis 读取数据并存储到 DuckDB
    
    注意：
    - 本服务只负责数据写入，不提供查询功能
    - 查询功能请使用 HistoryQuery
    """
    
    def __init__(self, config: StorageServiceConfig):
        """
        初始化存储服务
        
        Args:
            config: 服务配置
        """
        self.config = config
        
        # 初始化 Redis 连接
        self.redis_client = redis.Redis(
            host=config.redis_host,
            port=config.redis_port,
            db=config.redis_db,
            password=config.redis_password,
            decode_responses=True,
        )
        
        # 测试 Redis 连接
        try:
            self.redis_client.ping()
            logger.info("Redis connection established in StorageService")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
        
        # 初始化消息总线（如果启用）
        self._bus: Optional[Any] = None
        self._service_registry: Optional[Any] = None
        if config.use_message_bus and MESSAGE_BUS_AVAILABLE:
            self._init_message_bus()
        
        # 初始化 DuckDB 连接
        db_path = Path(config.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(db_path))
        self._create_table()
        
        # 批量插入缓冲区
        self._buffer: List[Dict[str, Any]] = []
        self._buffer_size = BATCH_INSERT_SIZE
        
        # ID 计数器（应用层维护，避免每次都查询 MAX(id)）
        self._next_id = 1
        self._id_initialized = False
        
        # 组态信息（从消息总线或 Redis 读取）
        self._cycle_time: float = 0.5  # 默认值
        self._sample_interval: Optional[float] = None
        self._stored_params: Optional[List[str]] = None
        self._instances_info: Dict[str, Any] = {}
        
        # Clock 实例（用于控制采样周期）
        self._clock: Optional[Clock] = None
        
        # 最后写入时间戳（秒，time.time()）
        self._last_write_time: float = 0.0
        
        # 运行控制
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._config_subscribe_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # 健康状态（用于服务注册）
        self._health_status = "unknown"
        
        # 诊断提供者（可选）
        self._diagnostic_provider: Optional[Any] = None
        
        # 工作强度监测统计
        self._performance_stats = {
            "flush_count": 0,  # 缓冲区刷新次数
            "total_records_written": 0,  # 总写入记录数
            "flush_times": [],  # 每次刷新的耗时（秒）
            "redis_read_times": [],  # 每次 Redis 读取的耗时（秒）
            "sample_count": 0,  # 采样次数
            "max_buffer_size": 0,  # 最大缓冲区大小
            "last_stats_time": time.time(),  # 上次统计时间
        }
        self._max_flush_times = 100  # 最多保留100个刷新耗时记录
        self._max_redis_read_times = 100  # 最多保留100个 Redis 读取耗时记录
        
        logger.info(
            "StorageService initialized: redis=%s:%d/%d, db_path=%s, use_message_bus=%s",
            config.redis_host,
            config.redis_port,
            config.redis_db,
            config.db_path,
            config.use_message_bus and self._bus is not None,
        )
    
    def _init_message_bus(self) -> None:
        """初始化消息总线"""
        if not MESSAGE_BUS_AVAILABLE:
            logger.warning("消息总线不可用，将回退到从 Redis 读取配置")
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
                    key_prefix="service_manager"  # 使用与ServiceManager相同的key_prefix
                )
            
            self._bus = MessageBus(bus_config)
            self._service_registry = ServiceRegistry(self._bus)
            logger.info("消息总线初始化成功，将订阅组态信息事件")
        except Exception as e:
            logger.error(f"消息总线初始化失败，将回退到从 Redis 读取配置: {e}", exc_info=True)
            self._bus = None
    
    def _create_table(self) -> None:
        """创建数据表结构"""
        try:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS data_records (
                    id BIGINT PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    param_name VARCHAR NOT NULL,
                    param_value DOUBLE NOT NULL,
                    instance_name VARCHAR NOT NULL,
                    param_type VARCHAR,
                    cycle_count INTEGER,
                    sim_time DOUBLE,
                    engine_id VARCHAR,
                    source_logic VARCHAR
                )
            """)
            
            # 创建索引
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp_param 
                ON data_records(timestamp, param_name)
            """)
            
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON data_records(timestamp)
            """)
            
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_param_name 
                ON data_records(param_name)
            """)
            
            # 创建覆盖索引（包含查询所需的所有列，减少回表查询）
            # 注意：DuckDB 会自动使用覆盖索引，如果索引包含查询所需的所有列
            try:
                self._conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_covering_query 
                    ON data_records(param_name, timestamp, param_value, instance_name, param_type, cycle_count, sim_time)
                """)
                logger.info("覆盖索引创建成功")
            except Exception as e:
                # 如果创建覆盖索引失败（可能因为列太多），记录警告但不影响功能
                logger.warning(f"创建覆盖索引失败（不影响功能）: {e}")
            
            logger.info("Database table and indexes created")
        except Exception as e:
            logger.error(f"Failed to create table: {e}", exc_info=True)
            raise
    
    def _apply_config(self, config_data: Dict[str, Any]) -> None:
        """
        应用组态信息
        
        Args:
            config_data: 组态信息字典
        """
        cycle_time = config_data.get("cycle_time", 0.5)
        sample_interval = config_data.get("sample_interval")
        stored_params = config_data.get("stored_params")
        instances_info = config_data.get("instances_info", {})
        
        # 检查配置是否有变化
        config_changed = (
            cycle_time != self._cycle_time or
            sample_interval != self._sample_interval or
            stored_params != self._stored_params
        )
        
        if config_changed:
            logger.info(
                "Config updated: cycle_time=%.3f, sample_interval=%s, stored_params=%s",
                cycle_time,
                sample_interval,
                len(stored_params) if stored_params else "all",
            )
            
            self._cycle_time = cycle_time
            self._sample_interval = sample_interval
            self._stored_params = stored_params
            self._instances_info = instances_info
            
            # 重新创建 Clock（使用 GENERATOR 模式，因为我们是独立进程）
            clock_config = ClockConfig(
                cycle_time=cycle_time,
                sample_interval=sample_interval,
                mode=ClockMode.GENERATOR,  # 独立进程不需要 sleep
                start_time=0.0,
            )
            self._clock = Clock(clock_config)
            self._clock.start()
    
    def _subscribe_config_events(self) -> None:
        """订阅组态信息事件（消息总线）"""
        if not self._bus:
            return
        
        try:
            def on_config_update(message):
                """处理组态信息更新事件"""
                try:
                    config_data = message.payload
                    self._apply_config(config_data)
                except Exception as e:
                    logger.error(f"Error processing config update event: {e}", exc_info=True)
            
            logger.info(f"Subscribing to config event: {CONFIG_EVENT}")
            self._bus.subscribe_events(
                [CONFIG_EVENT],
                on_config_update,
                timeout=None  # 无限等待
            )
        except Exception as e:
            logger.error(f"Error in config subscription loop: {e}", exc_info=True)
    
    def _read_data_from_redis(self) -> Optional[Dict[str, Any]]:
        """
        从 Redis 读取当前数据 (V2 模式：读取 Hash)
        
        Returns:
            数据字典，如果读取失败返回 None
        """
        read_start = time.time()
        try:
            # V2 模式：CURRENT_KEY 是一个 Hash
            fields_data = self.redis_client.hgetall(CURRENT_KEY)
            read_time = time.time() - read_start
            
            # 记录 Redis 读取耗时
            self._performance_stats["redis_read_times"].append(read_time)
            if len(self._performance_stats["redis_read_times"]) > self._max_redis_read_times:
                self._performance_stats["redis_read_times"].pop(0)
            
            if not fields_data:
                return None
            
            # 解析 V2 格式：每个 field 是 json
            params = {}
            sim_time = 0.0
            cycle_count = 0
            engine_map = {} # tag -> engine_id
            
            for tag, val_json in fields_data.items():
                try:
                    meta = json.loads(val_json)
                    params[tag] = meta.get("v", 0.0)
                    # 这里的 sim_time 和 cycle_count 如果是全局的，取最后一次更新的值
                    # 实际上 StorageService 基于自己的 Clock 运行，这里的 sim_time 仅作参考
                    if "t" in meta:
                        sim_time = max(sim_time, meta["t"])
                    engine_map[tag] = meta.get("e", "default")
                except:
                    continue
            
            return {
                "params": params,
                "engine_map": engine_map,
                "sim_time": sim_time,
                "cycle_count": 0, # 这里暂时填 0，或者从通知中获取
            }
        except Exception as e:
            logger.error(f"Failed to read data from Redis: {e}", exc_info=True)
            return None
    
    def _store_snapshot(self, data: Dict[str, Any], timestamp: datetime, need_sample: bool) -> None:
        """
        存储快照到 DuckDB（只在 need_sample=True 时存储）
        
        Args:
            data: 数据字典（包含 params）
            timestamp: 时间戳
            need_sample: 是否需要采样
        """
        if not need_sample:
            return
        
        try:
            params = data.get("params", {})
            engine_map = data.get("engine_map", {})
            cycle_count = data.get("cycle_count", 0)
            sim_time = data.get("sim_time", 0.0)
            
            # 准备记录
            records = []
            for param_name, param_value in params.items():
                # 如果指定了存储参数列表，只存储指定的参数
                if self._stored_params is not None:
                    if param_name not in self._stored_params:
                        continue
                
                # 只存储数值类型
                if not isinstance(param_value, (int, float)):
                    continue
                
                # 解析参数名
                # V2 中，如果位号名是 "engine_id.instance.tag"，则提取各部分
                # 这里保持向前兼容逻辑
                parts = param_name.split(".")
                if len(parts) >= 2:
                    instance_name = parts[-2]
                    param = parts[-1]
                else:
                    instance_name = "global"
                    param = param_name
                
                # 引擎 ID 与 来源逻辑
                current_eid = engine_map.get(param_name, "default")
                
                # 简单判断来源逻辑
                source_logic = "simulation"
                if "playback" in current_eid.lower():
                    source_logic = "playback"

                # 判断参数类型 (简单逻辑)
                param_type = "variable"
                
                record = {
                    "timestamp": timestamp,
                    "param_name": param_name,
                    "param_value": float(param_value),
                    "instance_name": instance_name,
                    "param_type": param_type,
                    "cycle_count": cycle_count,
                    "sim_time": sim_time,
                    "engine_id": current_eid,
                    "source_logic": source_logic
                }
                records.append(record)
            
            # 添加到缓冲区
            with self._lock:
                self._buffer.extend(records)
                
                # 更新最大缓冲区大小统计
                if len(self._buffer) > self._performance_stats["max_buffer_size"]:
                    self._performance_stats["max_buffer_size"] = len(self._buffer)
                
                # 如果缓冲区达到阈值，批量插入
                if len(self._buffer) >= self._buffer_size:
                    self._flush_buffer()
            
            # 更新统计
            self._performance_stats["sample_count"] += 1
            self._performance_stats["total_records_written"] += len(records)
            
            # 更新最后写入时间（无论是否真正 flush，都认为有新数据写入请求）
            self._last_write_time = time.time()
        except Exception as e:
            logger.error(f"Failed to store snapshot: {e}", exc_info=True)
    
    def _init_id_counter(self) -> None:
        """初始化 ID 计数器（只在第一次刷新时调用）"""
        if self._id_initialized:
            return
        
        try:
            result = self._conn.execute("SELECT COALESCE(MAX(id), 0) FROM data_records").fetchone()
            max_id = result[0] if result else 0
            self._next_id = max_id + 1
            self._id_initialized = True
            logger.debug("ID 计数器初始化: next_id=%d", self._next_id)
        except Exception as e:
            logger.warning(f"初始化 ID 计数器失败: {e}，使用默认值 1")
            self._next_id = 1
            self._id_initialized = True
    
    def _flush_buffer(self) -> None:
        """刷新缓冲区，批量插入数据（优化版本：使用批量 VALUES 语句）"""
        if not self._buffer:
            return
        
        flush_start = time.time()
        record_count = len(self._buffer)
        
        try:
            # 初始化 ID 计数器（只在第一次调用）
            self._init_id_counter()
            
            # 构建批量插入的 VALUES 子句
            # 格式: VALUES (?, ?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?, ?), ...
            values_clauses = []
            params = []
            start_id = self._next_id
            
            for i, record in enumerate(self._buffer):
                record_id = start_id + i
                values_clauses.append("(?, ?, ?, ?, ?, ?, ?, ?)")
                params.extend([
                    record_id,
                    record["timestamp"],
                    record["param_name"],
                    record["param_value"],
                    record["instance_name"],
                    record["param_type"],
                    record["cycle_count"],
                    record["sim_time"],
                ])
            
            # 构建完整的批量插入 SQL
            values_str = ", ".join(values_clauses)
            sql = f"""
                INSERT INTO data_records 
                (id, timestamp, param_name, param_value, instance_name, param_type, cycle_count, sim_time, engine_id, source_logic)
                VALUES {values_str}
            """
            
            # 执行批量插入（一次性插入所有记录）
            self._conn.execute(sql, params)
            
            # 提交事务
            self._conn.commit()
            
            # 更新 ID 计数器
            self._next_id = start_id + record_count
            
            flush_time = time.time() - flush_start
            
            # 记录刷新耗时
            self._performance_stats["flush_count"] += 1
            self._performance_stats["flush_times"].append(flush_time)
            if len(self._performance_stats["flush_times"]) > self._max_flush_times:
                self._performance_stats["flush_times"].pop(0)
            
            logger.debug("批量插入成功: %d 条记录, 耗时=%.3f秒, 平均=%.3f秒/条", 
                        record_count, flush_time, flush_time / record_count if record_count > 0 else 0)
            
            # 清空缓冲区
            self._buffer.clear()
        except Exception as e:
            flush_time = time.time() - flush_start
            logger.warning(
                "批量插入失败: 记录数=%d, 耗时=%.3f秒, 错误=%s, 已回滚事务",
                record_count,
                flush_time,
                e,
                exc_info=True,
            )
            self._conn.rollback()
            self._buffer.clear()
            # 如果插入失败，重置 ID 计数器，下次重新查询
            self._id_initialized = False
    
    def _run_loop(self) -> None:
        """
        主运行循环
        
        优化说明：
        - 循环频率由 Clock 的 cycle_time 控制，而不是固定的 update_cycle
        - 只在 need_sample=True 时才读取 Redis 并存储数据，大幅减少不必要的读取
        - 如果 sample_interval=10s，则每 10s 才读取一次 Redis（而不是每 100ms）
        """
        logger.info("StorageService started")
        
        # 无消息总线时无法接收组态事件，仅保持等待状态
        if not self._bus:
            logger.warning("MessageBus 不可用，StorageService 将等待组态事件，当前不会主动加载旧 Redis 组态键")
        
        # 如果未使用消息总线，定期检查配置更新
        last_config_check = time.time()
        config_check_interval = 1.0  # 每秒检查一次配置更新
        
        # 诊断更新间隔（秒）
        diagnostic_interval = 1.0
        last_diagnostic_update = 0.0
        
        # 工作强度统计输出间隔（秒）
        stats_log_interval = 10.0  # 每10秒输出一次工作强度统计
        last_stats_log = time.time()
        
        while self._running:
            try:
                cycle_start_time = time.time()
                
                # 未接入消息总线时仅维持心跳，不再轮询旧 Redis 组态键
                if not self._bus and time.time() - last_config_check >= config_check_interval:
                    last_config_check = time.time()
                
                # 更新服务健康状态和心跳（无论是否有 Clock，都要更新心跳）
                if self._service_registry:
                    try:
                        self._service_registry.update_heartbeat("storage_service")
                        # 如果没有 Clock（等待配置），健康状态应该是 "waiting" 而不是 "degraded"
                        if self._clock is None:
                            health_status = "waiting"
                        else:
                            health_status = "healthy" if self._health_status == "healthy" else "degraded"
                        self._service_registry.update_health("storage_service", health_status)
                    except Exception:
                        pass  # 忽略健康检查更新错误
                
                # 定期更新诊断信息（无论是否有 Clock，都要更新诊断信息）
                current_time = time.time()
                if current_time - last_diagnostic_update >= diagnostic_interval:
                    if self._diagnostic_provider:
                        try:
                            self._diagnostic_provider.push_diagnostics()
                            last_diagnostic_update = current_time
                        except Exception as e:
                            logger.debug(f"Failed to update diagnostics: {e}")
                
                # 定期输出工作强度统计
                if current_time - last_stats_log >= stats_log_interval:
                    self._log_performance_stats()
                    last_stats_log = current_time
                
                # 如果没有 Clock，等待配置
                if self._clock is None:
                    time.sleep(0.1)
                    continue
                
                # 使用 Clock 控制采样周期
                cycle_count, need_sample, time_str, _ = self._clock.step()
                
                # 优化：只在 need_sample=True 时才读取 Redis 并存储数据
                # 这样可以大幅减少不必要的 Redis 读取
                # 例如：如果 sample_interval=10s，则每 10s 才读取一次 Redis
                if need_sample:
                    # 从 Redis 读取数据
                    data = self._read_data_from_redis()
                    if data:
                        # 存储数据
                        timestamp = datetime.now()
                        self._store_snapshot(data, timestamp, need_sample)
                        self._health_status = "healthy"
                    else:
                        # 如果没有数据，标记为等待状态
                        self._health_status = "waiting"
                
                # 根据 Clock 的 cycle_time 控制循环频率（而不是固定的 update_cycle）
                # 这样循环频率与 Clock 周期完全匹配，确保周期计数准确
                cycle_time = time.time() - cycle_start_time
                sleep_time = max(0, self._clock.config.cycle_time - cycle_time)
                if sleep_time > 0:
                    time.sleep(sleep_time)
            except Exception as e:
                logger.error(f"Error in run loop: {e}", exc_info=True)
                time.sleep(0.1)
        
        # 刷新剩余缓冲区
        with self._lock:
            if self._buffer:
                self._flush_buffer()
        
        logger.info("StorageService stopped")
    
    def _log_performance_stats(self) -> None:
        """输出工作强度统计到日志"""
        stats = self._performance_stats
        elapsed_time = time.time() - stats["last_stats_time"]
        
        if elapsed_time <= 0:
            return
        
        # 计算写入速率
        write_rate = stats["total_records_written"] / elapsed_time if elapsed_time > 0 else 0.0
        sample_rate = stats["sample_count"] / elapsed_time if elapsed_time > 0 else 0.0
        flush_rate = stats["flush_count"] / elapsed_time if elapsed_time > 0 else 0.0
        
        # 计算平均耗时
        avg_flush_time = 0.0
        max_flush_time = 0.0
        min_flush_time = 0.0
        if stats["flush_times"]:
            avg_flush_time = sum(stats["flush_times"]) / len(stats["flush_times"])
            max_flush_time = max(stats["flush_times"])
            min_flush_time = min(stats["flush_times"])
        
        avg_redis_read_time = 0.0
        max_redis_read_time = 0.0
        if stats["redis_read_times"]:
            avg_redis_read_time = sum(stats["redis_read_times"]) / len(stats["redis_read_times"])
            max_redis_read_time = max(stats["redis_read_times"])
        
        # 当前缓冲区大小
        current_buffer_size = len(self._buffer) if hasattr(self, '_buffer') else 0
        
        logger.info(
            "=== StorageService 工作强度统计 (过去 %.1f 秒) ===",
            elapsed_time
        )
        logger.info(
            "  写入性能: 总记录数=%d, 写入速率=%.1f 记录/秒, 采样速率=%.2f 次/秒",
            stats["total_records_written"],
            write_rate,
            sample_rate
        )
        logger.info(
            "  缓冲区刷新: 刷新次数=%d, 刷新速率=%.2f 次/秒",
            stats["flush_count"],
            flush_rate
        )
        if stats["flush_times"]:
            logger.info(
                "  数据库写入耗时: 平均=%.3f秒, 最大=%.3f秒, 最小=%.3f秒",
                avg_flush_time,
                max_flush_time,
                min_flush_time
            )
        if stats["redis_read_times"]:
            logger.info(
                "  Redis读取耗时: 平均=%.3f秒, 最大=%.3f秒",
                avg_redis_read_time,
                max_redis_read_time
            )
        logger.info(
            "  缓冲区状态: 当前大小=%d, 最大大小=%d, 阈值=%d",
            current_buffer_size,
            stats["max_buffer_size"],
            self._buffer_size if hasattr(self, '_buffer_size') else 0
        )
        
        # 重置统计（保留耗时记录用于趋势分析）
        stats["total_records_written"] = 0
        stats["sample_count"] = 0
        stats["flush_count"] = 0
        stats["max_buffer_size"] = current_buffer_size  # 保留当前值作为新的基准
        stats["last_stats_time"] = time.time()
    
    def _init_diagnostics(self) -> None:
        """初始化诊断提供者"""
        try:
            from datacenter.diagnostics import StorageDiagnosticProvider
            
            self._diagnostic_provider = StorageDiagnosticProvider(self, self.redis_client)
            logger.info("诊断提供者已初始化")
        except ImportError:
            logger.debug("诊断模块不可用，跳过诊断初始化")
        except Exception as e:
            logger.warning(f"诊断提供者初始化失败: {e}", exc_info=True)
    
    def start(self) -> None:
        """启动存储服务"""
        if self._running:
            return
        
        # 初始化诊断提供者
        self._init_diagnostics()
        
        # 注册服务（如果使用消息总线）
        if self._service_registry:
            try:
                self._service_registry.register(
                    "storage_service",
                    metadata={
                        "version": "1.0.0",
                        "description": "存储服务",
                        "capabilities": ["history_storage", "data_query"],
                        "status": "starting",
                        "db_path": self.config.db_path,
                    }
                )
                logger.info("服务已注册: storage_service")
            except Exception as e:
                logger.warning(f"Failed to register service: {e}")
        
        self._running = True
        
        # 启动配置订阅线程（如果使用消息总线）
        if self._bus:
            self._config_subscribe_thread = threading.Thread(
                target=self._subscribe_config_events,
                daemon=True
            )
            self._config_subscribe_thread.start()
            logger.info("Config subscription thread started")
            
            # 组态仅由消息总线驱动，移除旧 Redis 组态键兜底读取
        else:
            logger.warning("MessageBus 不可用：StorageService 无法自动接收组态，将维持 waiting 状态")
        
        # 启动主循环线程
        self._thread = threading.Thread(target=self._run_loop, daemon=False)
        self._thread.start()
        logger.info("StorageService thread started")
        
        # 更新服务状态（初始状态为 waiting，等待配置）
        if self._service_registry:
            try:
                # 如果已经有 Clock，说明配置已加载，状态为 healthy
                # 否则为 waiting（等待配置）
                initial_status = "healthy" if self._clock is not None else "waiting"
                self._service_registry.update_health("storage_service", initial_status)
            except Exception:
                pass
    
    def stop(self) -> None:
        """停止历史数据服务"""
        if not self._running:
            return
        
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        if self._config_subscribe_thread:
            self._config_subscribe_thread.join(timeout=2)
        logger.info("StorageService stopped")
    
    def close(self) -> None:
        """关闭服务，释放资源"""
        self.stop()
        
        # 刷新缓冲区
        with self._lock:
            if self._buffer:
                self._flush_buffer()
        
        # 关闭消息总线
        try:
            if self._bus:
                self._bus.close()
                logger.info("消息总线连接已关闭")
        except Exception as e:
            logger.error(f"Failed to close message bus: {e}", exc_info=True)
        
        # 关闭数据库连接
        try:
            if self._conn:
                self._conn.close()
                logger.info("DuckDB connection closed")
        except Exception as e:
            logger.error(f"Failed to close DuckDB connection: {e}", exc_info=True)
        
        # 关闭 Redis 连接
        try:
            if self.redis_client:
                self.redis_client.close()
                logger.info("Redis connection closed")
        except Exception as e:
            logger.error(f"Failed to close Redis connection: {e}", exc_info=True)
    
    # ========== 查询接口（已废弃，保留用于向后兼容） ==========
    # 注意：查询功能已迁移到 HistoryQuery
    # 以下方法保留用于向后兼容，但强烈建议使用 HistoryQuery
    # HistoryQuery 使用只读连接，不会与写入操作冲突，性能更好
    def query_history(
        self,
        param_name: Optional[str] = None,
        instance_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        查询历史数据（已废弃）
        
        ⚠️ 此方法已废弃，请使用 HistoryQuery.query_history
        
        Args:
            param_name: 参数名称（可选），如 "tank1.level"
            instance_name: 实例名称（可选），如 "tank1"
            start_time: 开始时间（可选）
            end_time: 结束时间（可选）
            limit: 返回记录数限制，默认 1000
        
        Returns:
            历史数据记录列表
        """
        try:
            conditions = []
            params = []
            
            if param_name:
                conditions.append("param_name = ?")
                params.append(param_name)
            
            if instance_name:
                conditions.append("instance_name = ?")
                params.append(instance_name)
            
            if start_time:
                conditions.append("timestamp >= ?")
                params.append(start_time)
            
            if end_time:
                conditions.append("timestamp <= ?")
                params.append(end_time)
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            sql = f"""
                SELECT id, timestamp, param_name, param_value, instance_name, param_type, cycle_count, sim_time
                FROM data_records
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT ?
            """
            params.append(limit)
            
            result = self._conn.execute(sql, params).fetchall()
            
            records = []
            for row in result:
                records.append({
                    "id": row[0],
                    "timestamp": row[1].isoformat() if isinstance(row[1], datetime) else str(row[1]),
                    "param_name": row[2],
                    "param_value": row[3],
                    "instance_name": row[4],
                    "param_type": row[5],
                    "cycle_count": row[6],
                    "sim_time": row[7],
                })
            
            return records
        except Exception as e:
            logger.error(f"Failed to query history: {e}", exc_info=True)
            return []
    
    # 注意：此方法已废弃，请使用 HistoryQuery.query_sampled
    def query_sampled(
        self,
        param_name: Optional[str] = None,
        instance_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        sample_interval: Optional[float] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        采样查询（已废弃）
        
        ⚠️ 此方法已废弃，请使用 HistoryQuery.query_sampled
        
        使用SQL层面的时间桶采样，避免Python遍历和大量IN查询，提升性能60-80%
        
        Args:
            param_name: 参数名称（可选）
            instance_name: 实例名称（可选）
            start_time: 开始时间（可选）
            end_time: 结束时间（可选）
            sample_interval: 采样间隔（秒）
            limit: 返回记录数限制，默认 1000
        
        Returns:
            采样后的历史数据记录列表
        """
        try:
            if sample_interval is None or sample_interval <= 0:
                return self.query_history(
                    param_name=param_name,
                    instance_name=instance_name,
                    start_time=start_time,
                    end_time=end_time,
                    limit=limit,
                )
            
            # 必须提供 start_time 和 end_time 才能使用优化算法
            if not start_time or not end_time:
                # 如果没有提供时间范围，回退到旧算法
                return self._query_sampled_legacy(
                    param_name=param_name,
                    instance_name=instance_name,
                    start_time=start_time,
                    end_time=end_time,
                    sample_interval=sample_interval,
                    limit=limit,
                )
            
            conditions = []
            params = []
            
            if param_name:
                conditions.append("param_name = ?")
                params.append(param_name)
            
            if instance_name:
                conditions.append("instance_name = ?")
                params.append(instance_name)
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            # 优化算法：使用SQL时间桶采样
            # 将时间戳转换为时间桶编号，每个桶代表一个采样间隔
            # 使用窗口函数找到每个桶中最近的一条记录
            sql = f"""
                WITH time_buckets AS (
                    SELECT 
                        *,
                        FLOOR(EXTRACT(EPOCH FROM (timestamp - ?)) / ?) AS bucket_id
                    FROM data_records
                    WHERE {where_clause}
                      AND timestamp >= ?
                      AND timestamp <= ?
                ),
                sampled_data AS (
                    SELECT 
                        *,
                        ROW_NUMBER() OVER (PARTITION BY bucket_id ORDER BY timestamp DESC) AS rn
                    FROM time_buckets
                )
                SELECT 
                    id, timestamp, param_name, param_value, instance_name, param_type, cycle_count, sim_time
                FROM sampled_data
                WHERE rn = 1
                ORDER BY timestamp DESC
                LIMIT ?
            """
            
            # 参数顺序：start_time, sample_interval, ...其他条件参数..., start_time, end_time, limit
            query_params = [start_time, sample_interval] + params + [start_time, end_time, limit]
            
            logger.debug(f"优化查询SQL: {sql[:200]}..., 参数数量: {len(query_params)}")
            result = self._conn.execute(sql, query_params).fetchall()
            logger.debug(f"优化查询结果: {len(result)} 条记录")
            
            records = []
            for row in result:
                records.append({
                    "id": row[0],
                    "timestamp": row[1].isoformat() if isinstance(row[1], datetime) else str(row[1]),
                    "param_name": row[2],
                    "param_value": row[3],
                    "instance_name": row[4],
                    "param_type": row[5],
                    "cycle_count": row[6],
                    "sim_time": row[7],
                })
            
            return records
        except Exception as e:
            logger.error(f"Failed to query sampled (optimized): {e}", exc_info=True)
            # 如果优化算法失败，回退到旧算法
            logger.warning("回退到旧版查询算法")
            return self._query_sampled_legacy(
                param_name=param_name,
                instance_name=instance_name,
                start_time=start_time,
                end_time=end_time,
                sample_interval=sample_interval,
                limit=limit,
            )
    
    def _query_sampled_legacy(
        self,
        param_name: Optional[str] = None,
        instance_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        sample_interval: Optional[float] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        旧版采样查询（保留作为回退方案）
        
        当优化算法失败或条件不满足时使用
        """
        try:
            conditions = []
            params = []
            
            if param_name:
                conditions.append("param_name = ?")
                params.append(param_name)
            
            if instance_name:
                conditions.append("instance_name = ?")
                params.append(instance_name)
            
            if start_time:
                conditions.append("timestamp >= ?")
                params.append(start_time)
            
            if end_time:
                conditions.append("timestamp <= ?")
                params.append(end_time)
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            sql = f"""
                SELECT DISTINCT timestamp
                FROM data_records
                WHERE {where_clause}
                ORDER BY timestamp ASC
            """
            
            logger.debug(f"旧版查询时间戳SQL: {sql}, 参数: {params}")
            all_timestamps = self._conn.execute(sql, params).fetchall()
            logger.debug(f"查询到 {len(all_timestamps)} 个时间戳")
            
            # 如果没有查询到时间戳，检查数据库中是否有该参数的数据
            if len(all_timestamps) == 0 and param_name:
                check_sql = "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM data_records WHERE param_name = ?"
                check_result = self._conn.execute(check_sql, [param_name]).fetchone()
                if check_result:
                    count, min_ts, max_ts = check_result
                    logger.warning(f"参数 {param_name} 在数据库中有 {count} 条记录，时间范围: {min_ts} 到 {max_ts}")
                    if start_time and end_time:
                        logger.warning(f"查询时间范围: {start_time} 到 {end_time}")
            
            sampled_timestamps = []
            last_sampled_time = None
            
            for row in all_timestamps:
                ts = row[0]
                if isinstance(ts, datetime):
                    ts_timestamp = ts.timestamp()
                else:
                    ts_timestamp = float(ts)
                
                if last_sampled_time is None:
                    sampled_timestamps.append(ts)
                    last_sampled_time = ts_timestamp
                else:
                    time_diff = ts_timestamp - last_sampled_time
                    if time_diff >= sample_interval:
                        sampled_timestamps.append(ts)
                        last_sampled_time = ts_timestamp
            
            if not sampled_timestamps:
                return []
            
            # 如果采样点太多，分批查询
            if len(sampled_timestamps) > 1000:
                # 分批查询，每批最多1000个
                all_records = []
                for i in range(0, len(sampled_timestamps), 1000):
                    batch_timestamps = sampled_timestamps[i:i+1000]
                    batch_conditions = conditions.copy()
                    batch_params = params.copy()
                    batch_conditions.append("timestamp IN ({})".format(",".join(["?"] * len(batch_timestamps))))
                    batch_params.extend(batch_timestamps)
                    batch_where = " AND ".join(batch_conditions)
                    batch_sql = f"""
                        SELECT id, timestamp, param_name, param_value, instance_name, param_type, cycle_count, sim_time
                        FROM data_records
                        WHERE {batch_where}
                        ORDER BY timestamp DESC
                    """
                    batch_result = self._conn.execute(batch_sql, batch_params).fetchall()
                    for row in batch_result:
                        all_records.append({
                            "id": row[0],
                            "timestamp": row[1].isoformat() if isinstance(row[1], datetime) else str(row[1]),
                            "param_name": row[2],
                            "param_value": row[3],
                            "instance_name": row[4],
                            "param_type": row[5],
                            "cycle_count": row[6],
                            "sim_time": row[7],
                        })
                # 去重并按时间排序
                seen = set()
                unique_records = []
                for record in sorted(all_records, key=lambda x: x['timestamp'], reverse=True):
                    key = (record['timestamp'], record['param_name'])
                    if key not in seen:
                        seen.add(key)
                        unique_records.append(record)
                return unique_records[:limit]
            else:
                conditions.append("timestamp IN ({})".format(",".join(["?"] * len(sampled_timestamps))))
                params.extend(sampled_timestamps)
                
                where_clause = " AND ".join(conditions)
                sql = f"""
                    SELECT id, timestamp, param_name, param_value, instance_name, param_type, cycle_count, sim_time
                    FROM data_records
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT ?
                """
                params.append(limit)
                
                result = self._conn.execute(sql, params).fetchall()
                
                records = []
                for row in result:
                    records.append({
                        "id": row[0],
                        "timestamp": row[1].isoformat() if isinstance(row[1], datetime) else str(row[1]),
                        "param_name": row[2],
                        "param_value": row[3],
                        "instance_name": row[4],
                        "param_type": row[5],
                        "cycle_count": row[6],
                        "sim_time": row[7],
                    })
                
                return records
        except Exception as e:
            logger.error(f"Failed to query sampled (legacy): {e}", exc_info=True)
            return []
    
    def get_statistics(
        self,
        param_name: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        获取统计信息
        
        Args:
            param_name: 参数名称
            start_time: 开始时间（可选）
            end_time: 结束时间（可选）
        
        Returns:
            统计信息字典
        """
        try:
            conditions = ["param_name = ?"]
            params = [param_name]
            
            if start_time:
                conditions.append("timestamp >= ?")
                params.append(start_time)
            
            if end_time:
                conditions.append("timestamp <= ?")
                params.append(end_time)
            
            where_clause = " AND ".join(conditions)
            sql = f"""
                SELECT 
                    COUNT(*) as count,
                    AVG(param_value) as avg,
                    MIN(param_value) as min,
                    MAX(param_value) as max,
                    STDDEV(param_value) as stddev
                FROM data_records
                WHERE {where_clause}
            """
            
            result = self._conn.execute(sql, params).fetchone()
            
            if result and result[0] > 0:
                return {
                    "count": result[0],
                    "avg": float(result[1]) if result[1] is not None else 0.0,
                    "min": float(result[2]) if result[2] is not None else 0.0,
                    "max": float(result[3]) if result[3] is not None else 0.0,
                    "stddev": float(result[4]) if result[4] is not None else 0.0,
                }
            else:
                return {
                    "count": 0,
                    "avg": 0.0,
                    "min": 0.0,
                    "max": 0.0,
                    "stddev": 0.0,
                }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}", exc_info=True)
            return {
                "count": 0,
                "avg": 0.0,
                "min": 0.0,
                "max": 0.0,
                "stddev": 0.0,
            }
    
    def get_latest_value(self, param_name: str) -> Optional[float]:
        """
        获取最新值
        
        Args:
            param_name: 参数名称
        
        Returns:
            最新值，如果不存在返回 None
        """
        try:
            sql = """
                SELECT param_value
                FROM data_records
                WHERE param_name = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """
            result = self._conn.execute(sql, [param_name]).fetchone()
            
            if result:
                return float(result[0])
            return None
        except Exception as e:
            logger.error(f"Failed to get latest value: {e}", exc_info=True)
            return None
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息供诊断使用"""
        stats = self._performance_stats
        
        avg_flush_time = 0.0
        if stats["flush_times"]:
            avg_flush_time = sum(stats["flush_times"]) / len(stats["flush_times"])
            
        avg_redis_read_time = 0.0
        if stats["redis_read_times"]:
            avg_redis_read_time = sum(stats["redis_read_times"]) / len(stats["redis_read_times"])

        return {
            "total_records": stats["total_records_written"],
            "flush_count": stats["flush_count"],
            "avg_flush_time_ms": round(avg_flush_time * 1000, 2),
            "max_buffer_size": stats["max_buffer_size"],
            "current_buffer": len(self._buffer) if hasattr(self, '_buffer') else 0,
            "avg_redis_read_ms": round(avg_redis_read_time * 1000, 2),
            "health_status": self._health_status
        }
