"""
实时常驻运行器。

- 服务启动时创建并常驻运行 UnifiedEngine（REALTIME 模式）
- 支持动态加载/修改/删除组态与实例
- 提供最新快照缓存供 API 查询
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

# 导入程序和函数（触发注册）
from components import programs  # noqa: F401
from components import functions  # noqa: F401

from controller.engine import UnifiedEngine
from controller.parser import DSLParser, ProgramConfig
from controller.clock import ClockMode


class RealtimeRunner:
    """管理常驻的实时引擎线程。"""

    def __init__(self, engine: UnifiedEngine) -> None:
        self.engine = engine
        self.engine.clock.config.mode = ClockMode.REALTIME
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._latest_snapshot: Dict[str, Any] = {}

    def start(self) -> None:
        """启动后台线程（若未启动）。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止后台线程。"""
        if not self._thread:
            return
        self._stop_event.set()
        self.engine.clock.stop()
        self._thread.join(timeout=5)

    def _loop(self) -> None:
        """循环运行引擎，缓存最新快照。"""
        from components.utils.logger import get_logger
        import time
        logger = get_logger()
        
        # 心跳更新间隔（秒）
        heartbeat_interval = 5.0
        last_heartbeat = 0.0
        
        # 诊断更新间隔（秒）
        diagnostic_interval = 1.0  # Engine 服务使用1秒更新频率
        last_diagnostic_update = 0.0
        
        try:
            for snapshot in self.engine.run_realtime():
                self._latest_snapshot = snapshot
                
                # 定期更新心跳（如果Engine有ServiceRegistry）
                current_time = time.time()
                if current_time - last_heartbeat >= heartbeat_interval:
                    if hasattr(self.engine, '_service_registry') and self.engine._service_registry:
                        try:
                            self.engine._service_registry.update_heartbeat("engine")
                            last_heartbeat = current_time
                        except Exception as e:
                            logger.debug(f"Failed to update heartbeat: {e}")
                
                # 定期更新诊断信息
                if current_time - last_diagnostic_update >= diagnostic_interval:
                    if hasattr(self.engine, 'update_diagnostics'):
                        try:
                            self.engine.update_diagnostics()
                            last_diagnostic_update = current_time
                        except Exception as e:
                            logger.debug(f"Failed to update diagnostics: {e}")
                
                if self._stop_event.is_set():
                    break
        except Exception as e:
            logger.error(f"RealtimeRunner 循环异常: {e}", exc_info=True)
            # 重置快照为空字典，避免返回旧数据
            self._latest_snapshot = {}

    def latest_snapshot(self) -> Dict[str, Any]:
        """获取最新快照。"""
        return self._latest_snapshot

    # ---- 动态操作封装 -------------------------------------------------
    def load_config(self, config: ProgramConfig, namespace: str = "") -> None:
        self.engine.load_config(config, namespace=namespace)

    def patch_instance_params(self, name: str, params: Dict[str, Any]) -> None:
        for k, v in params.items():
            self.engine.queue_param_update(name, k, v)

    def patch_variable(self, name: str, expression: str | None, value: Any | None) -> None:
        self.engine.queue_variable_update(name, expression, value)

    def add_program_item(self, item) -> None:
        self.engine.queue_add_program(item)

    def add_variable_item(self, item) -> None:
        self.engine.queue_add_variable(item)

    def delete_program(self, name: str) -> None:
        self.engine.queue_delete_instance(name)

    def delete_variable(self, name: str) -> None:
        self.engine.queue_delete_variable(name)


def create_default_runner() -> RealtimeRunner:
    """创建一个空组态的实时运行器。"""
    parser = DSLParser()
    # 构建空配置
    empty_config = ProgramConfig(clock=parser._parse_clock_config({}), program=[], record_length=0, lag_requirements={})
    engine = UnifiedEngine.from_program_config(empty_config)
    runner = RealtimeRunner(engine)
    runner.start()
    return runner

