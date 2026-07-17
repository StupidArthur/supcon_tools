"""
Engine 诊断提供者

收集 Engine 服务的诊断信息
"""
from typing import Dict, Any, List
import time

from components.diagnostics.base import DiagnosticProvider, DiagnosticItem
from controller.engine import UnifiedEngine
from controller.expression import ExpressionNode, AlgorithmNode


class EngineDiagnosticProvider(DiagnosticProvider):
    """Engine 诊断提供者"""
    
    def __init__(self, engine: UnifiedEngine, redis_client):
        """
        初始化 Engine 诊断提供者
        
        Args:
            engine: UnifiedEngine 实例
            redis_client: Redis 客户端实例
        """
        super().__init__("engine", redis_client)
        self.engine = engine
        self._execution_times: List[float] = []  # 用于计算平均执行时间
        self._max_execution_times = 100  # 最多保留100个执行时间记录
        self._start_time: float = time.time()  # 记录启动时间
        self._publish_count: int = 0  # 发布计数
        self._last_publish_time: float = 0.0  # 最后发布时间
        self._publish_rate_start_time: float = time.time()  # 发布速率计算起始时间
        self._publish_rate_count: int = 0  # 发布速率计数器
        self._opcua_write_count: int = 0  # OPCUA写命令计数
    
    def get_diagnostic_schema(self) -> Dict[str, Any]:
        """
        返回诊断结构定义
        
        Returns:
            诊断结构字典
        """
        return {
            "items": [
                # 基础信息
                {"name": "cycle_count", "unit": "", "description": "当前周期计数", "data_type": "int"},
                {"name": "sim_time", "unit": "s", "description": "当前模拟时间", "data_type": "float"},
                {"name": "uptime", "unit": "s", "description": "运行时长", "data_type": "float"},
                {"name": "real_time_ratio", "unit": "", "description": "实时比（模拟时间/实际时间）", "data_type": "float"},
                
                # 节点和实例统计
                {"name": "node_count", "unit": "", "description": "总节点数量", "data_type": "int"},
                {"name": "expression_node_count", "unit": "", "description": "表达式节点数量", "data_type": "int"},
                {"name": "algorithm_node_count", "unit": "", "description": "算法节点数量", "data_type": "int"},
                {"name": "variable_count", "unit": "", "description": "变量数量", "data_type": "int"},
                {"name": "instance_count", "unit": "", "description": "实例数量", "data_type": "int"},
                
                # 时间配置
                {"name": "cycle_time", "unit": "s", "description": "执行周期时间", "data_type": "float"},
                {"name": "clock_mode", "unit": "", "description": "时钟模式", "data_type": "string"},
                
                # 执行时间统计
                {"name": "avg_execution_time", "unit": "ms", "description": "平均执行时间", "data_type": "float"},
                {"name": "max_execution_time", "unit": "ms", "description": "最大执行时间", "data_type": "float"},
                {"name": "min_execution_time", "unit": "ms", "description": "最小执行时间", "data_type": "float"},
                {"name": "p95_execution_time", "unit": "ms", "description": "P95执行时间", "data_type": "float"},
                {"name": "execution_time_ratio", "unit": "", "description": "执行时间占比", "data_type": "float"},
                
                # 数据发布
                {"name": "snapshot_publish_rate", "unit": "次/秒", "description": "快照发布速率", "data_type": "float"},
                {"name": "redis_connection_status", "unit": "", "description": "Redis连接状态", "data_type": "string"},
                {"name": "last_publish_time", "unit": "", "description": "最后发布时间", "data_type": "string"},
                
                # 消息总线
                {"name": "message_bus_status", "unit": "", "description": "消息总线连接状态", "data_type": "string"},
                {"name": "message_server_running", "unit": "", "description": "消息服务器运行状态", "data_type": "bool"},
                {"name": "opcua_write_command_count", "unit": "", "description": "OPCUA写命令接收次数", "data_type": "int"},
                
                # 待处理更新
                {"name": "pending_updates", "unit": "", "description": "待处理更新数量", "data_type": "int"},
            ],
            "update_interval": 1.0,  # 每1秒更新一次
        }
    
    def collect_diagnostics(self) -> List[DiagnosticItem]:
        """
        收集诊断数据
        
        Returns:
            诊断项列表
        """
        items = []
        
        try:
            from datetime import datetime
            
            # ========== 基础信息 ==========
            # 周期计数
            items.append(DiagnosticItem(
                name="cycle_count",
                value=self.engine.clock.cycle_count,
                unit="",
                description="当前周期计数",
                data_type="int"
            ))
            
            # 模拟时间
            sim_time = self.engine.clock.sim_time if hasattr(self.engine.clock, 'sim_time') else 0.0
            items.append(DiagnosticItem(
                name="sim_time",
                value=round(sim_time, 3),
                unit="s",
                description="当前模拟时间",
                data_type="float"
            ))
            
            # 运行时长
            uptime = time.time() - self._start_time
            items.append(DiagnosticItem(
                name="uptime",
                value=round(uptime, 2),
                unit="s",
                description="运行时长",
                data_type="float"
            ))
            
            # 实时比
            real_time_ratio = sim_time / uptime if uptime > 0 else 0.0
            items.append(DiagnosticItem(
                name="real_time_ratio",
                value=round(real_time_ratio, 4),
                unit="",
                description="实时比（模拟时间/实际时间）",
                data_type="float"
            ))
            
            # ========== 节点和实例统计 ==========
            # 总节点数量
            node_count = len(self.engine._nodes) if hasattr(self.engine, '_nodes') else 0
            items.append(DiagnosticItem(
                name="node_count",
                value=node_count,
                unit="",
                description="总节点数量",
                data_type="int"
            ))
            
            # 节点分类统计
            expression_node_count = 0
            algorithm_node_count = 0
            if hasattr(self.engine, '_nodes') and self.engine._nodes:
                for node in self.engine._nodes:
                    if isinstance(node, ExpressionNode):
                        expression_node_count += 1
                    elif isinstance(node, AlgorithmNode):
                        algorithm_node_count += 1
            
            items.append(DiagnosticItem(
                name="expression_node_count",
                value=expression_node_count,
                unit="",
                description="表达式节点数量",
                data_type="int"
            ))
            
            items.append(DiagnosticItem(
                name="algorithm_node_count",
                value=algorithm_node_count,
                unit="",
                description="算法节点数量",
                data_type="int"
            ))
            
            # 变量数量
            variable_count = len(self.engine.vars._variables) if hasattr(self.engine.vars, '_variables') else 0
            items.append(DiagnosticItem(
                name="variable_count",
                value=variable_count,
                unit="",
                description="变量数量",
                data_type="int"
            ))
            
            # 实例数量
            instance_count = len(self.engine._instances) if hasattr(self.engine, '_instances') else 0
            items.append(DiagnosticItem(
                name="instance_count",
                value=instance_count,
                unit="",
                description="实例数量",
                data_type="int"
            ))
            
            # ========== 时间配置 ==========
            # 执行周期时间
            cycle_time = self.engine.clock.config.cycle_time if hasattr(self.engine.clock, 'config') else 0.0
            items.append(DiagnosticItem(
                name="cycle_time",
                value=cycle_time,
                unit="s",
                description="执行周期时间",
                data_type="float"
            ))
            
            # 时钟模式
            clock_mode = self.engine.clock.config.mode.name if hasattr(self.engine.clock, 'config') and hasattr(self.engine.clock.config, 'mode') else "unknown"
            items.append(DiagnosticItem(
                name="clock_mode",
                value=clock_mode,
                unit="",
                description="时钟模式",
                data_type="string"
            ))
            
            # ========== 执行时间统计 ==========
            if self._execution_times:
                sorted_times = sorted(self._execution_times)
                avg_time = sum(sorted_times) / len(sorted_times)
                max_time = max(sorted_times)
                min_time = min(sorted_times)
                
                # P95计算
                p95_index = int(len(sorted_times) * 0.95)
                p95_time = sorted_times[p95_index] if p95_index < len(sorted_times) else sorted_times[-1]
                
                # 执行时间占比
                execution_ratio = avg_time / cycle_time if cycle_time > 0 else 0.0
                
                items.append(DiagnosticItem(
                    name="avg_execution_time",
                    value=round(avg_time * 1000, 2),
                    unit="ms",
                    description="平均执行时间",
                    data_type="float"
                ))
                
                items.append(DiagnosticItem(
                    name="max_execution_time",
                    value=round(max_time * 1000, 2),
                    unit="ms",
                    description="最大执行时间",
                    data_type="float"
                ))
                
                items.append(DiagnosticItem(
                    name="min_execution_time",
                    value=round(min_time * 1000, 2),
                    unit="ms",
                    description="最小执行时间",
                    data_type="float"
                ))
                
                items.append(DiagnosticItem(
                    name="p95_execution_time",
                    value=round(p95_time * 1000, 2),
                    unit="ms",
                    description="P95执行时间",
                    data_type="float"
                ))
                
                items.append(DiagnosticItem(
                    name="execution_time_ratio",
                    value=round(execution_ratio, 4),
                    unit="",
                    description="执行时间占比",
                    data_type="float"
                ))
            else:
                # 如果没有执行时间记录，返回默认值
                for name in ["avg_execution_time", "max_execution_time", "min_execution_time", "p95_execution_time"]:
                    items.append(DiagnosticItem(
                        name=name,
                        value=0.0,
                        unit="ms",
                        description=name.replace("_", " ").title(),
                        data_type="float"
                    ))
                items.append(DiagnosticItem(
                    name="execution_time_ratio",
                    value=0.0,
                    unit="",
                    description="执行时间占比",
                    data_type="float"
                ))
            
            # ========== 数据发布统计 ==========
            # 快照发布速率（基于最近5秒的发布次数）
            current_time = time.time()
            time_elapsed = current_time - self._publish_rate_start_time
            if time_elapsed > 0:
                publish_rate = self._publish_rate_count / time_elapsed
            else:
                publish_rate = 0.0
            
            items.append(DiagnosticItem(
                name="snapshot_publish_rate",
                value=round(publish_rate, 2),
                unit="次/秒",
                description="快照发布速率",
                data_type="float"
            ))
            
            # Redis连接状态
            redis_status = "disconnected"
            if hasattr(self.engine, '_realtime_publisher') and self.engine._realtime_publisher:
                try:
                    if hasattr(self.engine._realtime_publisher, '_redis_client') and self.engine._realtime_publisher._redis_client:
                        self.engine._realtime_publisher._redis_client.ping()
                        redis_status = "connected"
                except Exception:
                    redis_status = "error"
            
            items.append(DiagnosticItem(
                name="redis_connection_status",
                value=redis_status,
                unit="",
                description="Redis连接状态",
                data_type="string"
            ))
            
            # 最后发布时间
            if self._last_publish_time > 0:
                last_publish_str = datetime.fromtimestamp(self._last_publish_time).strftime("%Y-%m-%d %H:%M:%S")
            else:
                last_publish_str = "从未发布"
            
            items.append(DiagnosticItem(
                name="last_publish_time",
                value=last_publish_str,
                unit="",
                description="最后发布时间",
                data_type="string"
            ))
            
            # ========== 消息总线状态 ==========
            # 消息总线连接状态
            message_bus_status = "not_initialized"
            if hasattr(self.engine, '_message_bus') and self.engine._message_bus:
                message_bus_status = "connected"
            elif hasattr(self.engine, '_message_bus') and self.engine._message_bus is None:
                message_bus_status = "disabled"
            
            items.append(DiagnosticItem(
                name="message_bus_status",
                value=message_bus_status,
                unit="",
                description="消息总线连接状态",
                data_type="string"
            ))
            
            # 消息服务器运行状态
            message_server_running = False
            if hasattr(self.engine, '_message_server') and self.engine._message_server:
                # MessageServer 内部有 _running 标志和 _thread 线程
                if hasattr(self.engine._message_server, '_running'):
                    message_server_running = self.engine._message_server._running
                # 同时检查线程是否存活（更可靠）
                if hasattr(self.engine._message_server, '_thread') and self.engine._message_server._thread:
                    message_server_running = message_server_running and self.engine._message_server._thread.is_alive()
            
            items.append(DiagnosticItem(
                name="message_server_running",
                value=message_server_running,
                unit="",
                description="消息服务器运行状态",
                data_type="bool"
            ))
            
            # OPCUA写命令计数
            items.append(DiagnosticItem(
                name="opcua_write_command_count",
                value=self._opcua_write_count,
                unit="",
                description="OPCUA写命令接收次数",
                data_type="int"
            ))
            
            # ========== 待处理更新 ==========
            pending_count = 0
            if hasattr(self.engine, '_pending_param_updates'):
                pending_count += len(self.engine._pending_param_updates)
            if hasattr(self.engine, '_pending_variable_updates'):
                pending_count += len(self.engine._pending_variable_updates)
            if hasattr(self.engine, '_pending_add_items'):
                pending_count += len(self.engine._pending_add_items)
            if hasattr(self.engine, '_pending_delete_instances'):
                pending_count += len(self.engine._pending_delete_instances)
            if hasattr(self.engine, '_pending_delete_variables'):
                pending_count += len(self.engine._pending_delete_variables)
            
            items.append(DiagnosticItem(
                name="pending_updates",
                value=pending_count,
                unit="",
                description="待处理更新数量",
                data_type="int"
            ))
            
        except Exception as e:
            # 如果收集过程中出错，至少返回一个错误项
            items.append(DiagnosticItem(
                name="error",
                value=str(e),
                unit="",
                description="诊断收集错误",
                data_type="string"
            ))
        
        return items
    
    def record_execution_time(self, execution_time: float) -> None:
        """
        记录执行时间（用于计算平均执行时间）
        
        Args:
            execution_time: 执行时间（秒）
        """
        self._execution_times.append(execution_time)
        # 只保留最近N个执行时间
        if len(self._execution_times) > self._max_execution_times:
            self._execution_times.pop(0)
    
    def record_publish(self) -> None:
        """记录快照发布"""
        self._publish_count += 1
        self._last_publish_time = time.time()
        self._publish_rate_count += 1
        
        # 每5秒重置一次速率计数器（用于计算最近5秒的发布速率）
        current_time = time.time()
        if current_time - self._publish_rate_start_time >= 5.0:
            self._publish_rate_start_time = current_time
            self._publish_rate_count = 0
    
    def record_opcua_write(self) -> None:
        """记录OPCUA写命令"""
        self._opcua_write_count += 1

