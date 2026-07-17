"""
回放引擎。

职责：
- 读取 Excel/CSV 文件
- 按时间顺序回放数据
- 适配 BaseRuntime 接口供 ServiceManager 调用
"""

from __future__ import annotations

import time
import pandas as pd
from pathlib import Path
from typing import Any, Dict, Optional, Iterable, List
from datetime import datetime

from components.utils.logger import get_logger
from .clock import Clock, ClockConfig, ClockMode
from .realtime_publisher import RealtimePublisher, RealtimeConfig

logger = get_logger()

class PlaybackEngine:
    """
    回放引擎
    """
    def __init__(
        self, 
        engine_id: str, 
        file_path: str, 
        time_col: Optional[str] = None, 
        sheet_name: str = "Sheet1", 
        cycle_time: float = 1.0
    ):
        self.engine_id = engine_id
        self.file_path = Path(file_path)
        self.time_col = time_col
        self.sheet_name = sheet_name
        
        # 时钟管理（兼容 RealtimeRunner）
        self.clock = Clock(ClockConfig(cycle_time=cycle_time, mode=ClockMode.REALTIME))
        
        self.df: Optional[pd.DataFrame] = None
        self._realtime_publisher: Optional[RealtimePublisher] = None
        
        # 消息总线支持（虽然回放通常只读，但也可能需要心跳）
        self._service_registry = None 
        self._diagnostic_provider = None
        self._current_index = 0
        
        self._load_data()

    def _load_data(self):
        """加载数据文件"""
        if not self.file_path.exists():
            raise FileNotFoundError(f"Playback file not found: {self.file_path}")
        
        try:
            if self.file_path.suffix.lower() == '.csv':
                self.df = pd.read_csv(self.file_path)
            elif self.file_path.suffix.lower() in ['.xls', '.xlsx']:
                self.df = pd.read_excel(self.file_path, sheet_name=self.sheet_name)
            else:
                raise ValueError(f"Unsupported file format: {self.file_path.suffix}")
            
            # 如果指定了时间列，按时间排序
            if self.time_col and self.time_col in self.df.columns:
                self.df.sort_values(by=self.time_col, inplace=True)
                logger.info(f"Loaded {len(self.df)} records from {self.file_path}, sorted by {self.time_col}")
            else:
                logger.info(f"Loaded {len(self.df)} records from {self.file_path} (sequential)")
                
        except Exception as e:
            logger.error(f"Failed to load data: {e}")
            raise

    def enable_realtime_data(self, config: RealtimeConfig, enable_message_bus: bool = False) -> None:
        """启用实时数据发布"""
        self._realtime_publisher = RealtimePublisher(config)
        
        if enable_message_bus and config.bus_config:
            # 初始化简单的服务注册
            try:
                from components.message_bus import MessageBus, ServiceRegistry
                self._message_bus = MessageBus(config.bus_config)
                self._service_registry = ServiceRegistry(self._message_bus)
                
                service_name = f"engine.{self.engine_id}"
                self._service_registry.register(
                    service_name,
                    metadata={
                        "type": "playback",
                        "engine_id": self.engine_id,
                        "status": "running",
                        "file": str(self.file_path)
                    }
                )
                logger.info(f"PlaybackEngine {service_name} registered to bus")
            except Exception as e:
                logger.warning(f"Failed to init message bus for playback engine: {e}")

        # 初始化诊断信息
        try:
            from controller.diagnostics.playback_diagnostics import PlaybackDiagnosticProvider
            import redis
            redis_client = redis.Redis(
                host=config.redis_host,
                port=config.redis_port,
                db=config.redis_db,
                password=config.redis_password,
                decode_responses=True
            )
            self._diagnostic_provider = PlaybackDiagnosticProvider(self, redis_client)
        except Exception as e:
            logger.debug(f"Failed to init diagnostics for playback: {e}")

    def run_realtime(self) -> Iterable[Dict[str, Any]]:
        """
        实时运行生成器
        """
        if self.df is None or self.df.empty:
            logger.warning("No data to playback")
            yield {}
            return

        records = self.df.to_dict('records')
        
        self.clock.start()
        cycle_count = 0
        
        # 简单的循环回放模式：播放完后是否循环？需求未定，暂时单次播放后停止或循环？
        # 假设：循环播放
        while True:
            for i, record in enumerate(records):
                step_start = time.time()
                
                # 1. 构造快照
                snapshot = {
                    "cycle_count": cycle_count,
                    "sim_time": self.clock.sim_time,
                    "time_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "exec_ratio": 0.0
                }
                
                # 填充 tag 数据
                for col, val in record.items():
                    if col == self.time_col:
                        continue
                    # 构造全名 tag
                    tag_name = f"{self.engine_id}.{col}"
                    snapshot[tag_name] = val
                    
                # 2. 推送数据
                if self._realtime_publisher:
                    try:
                        self._realtime_publisher.push_snapshot(snapshot)
                        if self._diagnostic_provider:
                            self._diagnostic_provider.increment_update_count()
                    except Exception as e:
                        logger.error(f"Push failed: {e}")

                self._current_index = i # 我们需要枚举 records
                yield snapshot
                
                # 3. 诊断与心跳
                if cycle_count % 100 == 0:
                    service_name = f"engine.{self.engine_id}"
                    if self._service_registry:
                        try:
                            self._service_registry.update_heartbeat(service_name)
                        except: pass
                    if self._diagnostic_provider:
                        try:
                            self._diagnostic_provider.push_diagnostics()
                        except: pass

                # 4. 时间控制
                self.clock.step(force_sleep=True) # 使用 Clock 的 sleep 机制
                cycle_count += 1
                
            logger.info("Playback loop completed, restarting...")
            # 循环播放

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息供诊断使用"""
        total_rows = len(self.df) if self.df is not None else 0
        return {
            "engine_id": self.engine_id,
            "engine_type": "playback",
            "cycle_count": self.clock.cycle_count,
            "sim_time": round(self.clock.sim_time, 3),
            "current_index": self._current_index,
            "total_records": total_rows,
            "progress": round((self._current_index / total_rows * 100), 1) if total_rows > 0 else 0
        }

    def close(self):
        if self._realtime_publisher:
            self._realtime_publisher.close()
        if self.clock:
            self.clock.stop()
