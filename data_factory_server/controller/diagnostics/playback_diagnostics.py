"""
回放引擎诊断提供者
"""

import json
import time
from typing import Any, Dict, List
import redis
from components.utils.logger import get_logger

logger = get_logger()

class PlaybackDiagnosticProvider:
    """
    为 PlaybackEngine 提供诊断信息，并将其实时推送到 Redis。
    """

    def __init__(self, engine: Any, redis_client: redis.Redis):
        self.engine = engine
        self.redis_client = redis_client
        self.engine_id = engine.engine_id
        self.redis_key = f"data_factory:diagnostic:engine.{self.engine_id}"
        
        self._update_count = 0
        self._start_time = time.time()

    def increment_update_count(self):
        """记录一次数据推送"""
        self._update_count += 1

    def push_diagnostics(self):
        """构造并推送诊断快照到 Redis"""
        try:
            uptime = time.time() - self._start_time
            
            # 基础信息
            items = [
                {"name": "engine_id", "value": self.engine_id, "description": "引擎实例ID"},
                {"name": "engine_type", "value": "playback", "description": "引擎类型"},
                {"name": "uptime", "value": round(uptime, 1), "unit": "s", "description": "运行时间"},
                {"name": "update_count", "value": self._update_count, "description": "累计推送次数"},
                {"name": "file_path", "value": str(self.engine.file_path), "description": "回放文件路径"},
            ]
            
            # 回放特有信息
            if self.engine.df is not None:
                items.append({"name": "total_records", "value": len(self.engine.df), "description": "总记录数"})
            
            if hasattr(self.engine, "_current_index"):
                 items.append({"name": "current_index", "value": self.engine._current_index, "description": "当前进度(行)"})
                 if len(self.engine.df) > 0:
                     progress = (self.engine._current_index / len(self.engine.df)) * 100
                     items.append({"name": "progress", "value": round(progress, 1), "unit": "%", "description": "回放进度"})

            diag_data = {
                "service": f"engine.{self.engine_id}",
                "timestamp": time.time(),
                "items": items
            }
            
            self.redis_client.set(self.redis_key, json.dumps(diag_data))
            
        except Exception as e:
            logger.debug(f"Failed to push playback diagnostics: {e}")
