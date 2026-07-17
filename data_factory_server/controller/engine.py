"""
统一执行引擎骨架

后续将作为：
- 实时运行（在线 mock）
- 快速批量生成（离线数据）
- 从文件播放（replay）
的统一调度入口。
"""

from __future__ import annotations

from dataclasses import dataclass
import ast
import threading
import os
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Iterable, Optional, Tuple

from .clock import Clock, ClockConfig, ClockMode, LAG_SAFETY_MARGIN
from .variable import VariableStore
from .expression import ExpressionNode, ExpressionConfig, AlgorithmNode, ExpressionEvaluator
from .factory import InstanceFactory
from .parser import ProgramConfig, ProgramItem, DEFAULT_PLOT_SCALE_REF
from components.utils.logger import get_logger

# 可选导入数据管理模块
try:
    from .realtime_publisher import RealtimePublisher, RealtimeConfig
    DATA_MANAGER_AVAILABLE = True
except ImportError:
    DATA_MANAGER_AVAILABLE = False
    RealtimePublisher = None
    RealtimeConfig = None

# 可选导入消息总线
try:
    from components.message_bus import MessageBus, BusConfig, MessageServer, MessageClient, ServiceRegistry
    MESSAGE_BUS_AVAILABLE = True
except ImportError:
    MESSAGE_BUS_AVAILABLE = False
    MessageBus = None
    BusConfig = None
    MessageServer = None
    MessageClient = None
    ServiceRegistry = None


logger = get_logger()


@dataclass
class EngineConfig:
    """
    执行引擎配置（初版，仅表达式节点）。

    后续可以扩展：
    - 物理模型节点
    - 控制算法节点
    - 播放节点（从 CSV/数据库读）
    
    注意：
        - 历史数据长度由 VariableStore 按变量配置，不再使用全局 max_lag_steps
    """

    clock: ClockConfig
    expressions: List[ExpressionConfig]


class UnifiedEngine:
    """
    统一执行引擎（初版实现：只包含表达式节点）。

    特点：
    - 内部使用 `Clock` 管理模拟时间与 sleep。
    - 使用 `VariableStore` 管理变量当前值与历史。
    - 通过 `ExpressionNode` 列表按顺序执行计算。
    """

    def __init__(self, config: EngineConfig, instances: Dict[str, Any] | None = None) -> None:
        self.config = config
        self.clock = Clock(config.clock)
        self.vars = VariableStore()
        self._factory = InstanceFactory(cycle_time=config.clock.cycle_time)
        self._instances: Dict[str, Any] = instances or {}
        self._nodes: List[Any] = []
        self._program_items: List[ProgramItem] = []
        # 变更队列（在周期空闲时应用）
        self._pending_param_updates: List[Tuple[str, str, Any]] = []
        self._pending_variable_updates: List[Tuple[str, str | None, Any | None]] = []
        self._pending_add_items: List[ProgramItem] = []
        self._pending_delete_instances: List[str] = []
        self._pending_delete_variables: List[str] = []
        self._lock = threading.RLock()
        # 只有在提供了 instances 时才创建表达式节点
        if instances is not None:
            self._expr_nodes: List[ExpressionNode] = [
                ExpressionNode(c, instances) for c in config.expressions
            ]
        else:
            self._expr_nodes: List[ExpressionNode] = []

        # 数据管理模块（可选）
        self._realtime_publisher: Any = None
        self.engine_id: str = "default"
        
        # 消息总线（可选，用于接收 OPCUA 写值命令和服务注册）
        self._message_bus: Any = None
        self._message_server: Any = None
        self._service_registry: Any = None
        
        # 诊断提供者（可选）
        self._diagnostic_provider: Any = None

        logger.info(
            "UnifiedEngine initialized: %d expression nodes",
            len(self._expr_nodes),
        )
    
    @classmethod
    def from_program_config(cls, config: ProgramConfig) -> "UnifiedEngine":
        """
        从ProgramConfig创建引擎。
        
        Args:
            config: 程序配置
            
        Returns:
            统一执行引擎实例
        """
        # 创建实例工厂
        factory = InstanceFactory(cycle_time=config.clock.cycle_time)
        
        # 创建所有实例和节点
        instances: Dict[str, Any] = {}
        nodes: List[Any] = []
        expressions: List[ExpressionConfig] = []
        
        for item in config.program:
            if item.type.upper() == "VARIABLE":
                # Variable类型：创建表达式节点
                expr_config = ExpressionConfig(name=item.name, expression=item.expression)
                expressions.append(expr_config)
            else:
                # 算法/模型类型：创建实例和算法节点
                instance = factory.create_instance(item)
                instances[item.name] = instance
                
                # 获取存储属性列表
                stored_attrs = getattr(instance.__class__, "stored_attributes", [])
                
                # 创建算法节点（暂时不传入vars_store，后续在引擎初始化后预编译）
                node = AlgorithmNode(
                    instance=instance,
                    expression=item.expression,
                    stored_attributes=stored_attrs,
                    instance_name=item.name,
                    instances=instances,
                )
                nodes.append(node)
        
        # 创建表达式节点（暂时不传入vars_store，后续在引擎初始化后预编译）
        expr_nodes: List[ExpressionNode] = []
        for expr_config in expressions:
            node = ExpressionNode(expr_config, instances)
            expr_nodes.append(node)
        
        # 创建引擎配置
        engine_config = EngineConfig(
            clock=config.clock,
            expressions=expressions,
        )
        
        # 创建引擎（传入 instances）
        engine = cls(engine_config, instances=instances)
        engine._nodes = nodes + expr_nodes
        engine._program_items = deepcopy(config.program)
        
        # 根据 lag_requirements 配置每个变量的历史数据长度
        # 只有需要历史数据的变量才创建历史缓冲区
        for var_name, max_lag_steps in config.lag_requirements.items():
            # 加上安全余量（使用常量 LAG_SAFETY_MARGIN）
            safe_lag_steps = int(max_lag_steps * LAG_SAFETY_MARGIN)
            engine.vars.configure_lag(var_name, safe_lag_steps)
            logger.debug(
                "配置变量历史数据: %s, max_lag_steps=%d (需求=%d)",
                var_name,
                safe_lag_steps,
                max_lag_steps,
            )
        
        # 初始化所有实例的属性到VariableStore
        for instance_name, instance in instances.items():
            stored_attrs = getattr(instance.__class__, "stored_attributes", [])
            for attr_name in stored_attrs:
                var_key = f"{instance_name}.{attr_name}"
                # 检查该属性是否需要历史数据
                if var_key in config.lag_requirements:
                    max_lag_steps = config.lag_requirements[var_key]
                    safe_lag_steps = int(max_lag_steps * LAG_SAFETY_MARGIN)
                    engine.vars.configure_lag(var_key, safe_lag_steps)
                    logger.debug(
                        "配置实例属性历史数据: %s, max_lag_steps=%d (需求=%d)",
                        var_key,
                        safe_lag_steps,
                        max_lag_steps,
                    )
                
                if hasattr(instance, attr_name):
                    value = getattr(instance, attr_name)
                    engine.vars.set(var_key, value)
        
        # 预编译所有节点以提升性能
        engine._precompile_nodes()
        
        return engine

    # 数据管理 API ------------------------------------------------------
    def enable_realtime_data(self, config: Any, enable_message_bus: bool = True) -> None:
        """
        启用实时数据发布（REALTIME 模式）
        
        启用后会自动推送组态信息到 Redis 和消息总线，供历史数据服务和 OPCUA Server 使用。
        
        Args:
            config: 实时数据配置（RealtimeConfig）
            enable_message_bus: 是否启用消息总线（用于接收 OPCUA 写值命令）
        """
        if not DATA_MANAGER_AVAILABLE:
            raise ImportError("datacenter module not available. Please install redis.")
        
        if RealtimePublisher is None:
            raise ImportError("RealtimePublisher not available. Please install redis.")
        
        self.engine_id = getattr(config, "engine_id", "default")
        self._realtime_publisher = RealtimePublisher(config)
        
        # 推送组态信息到 Redis 和消息总线（供历史数据服务和 OPCUA Server 使用）
        self._push_config_to_redis()
        
        # 启用消息总线（用于接收 OPCUA 写值命令）
        if enable_message_bus and MESSAGE_BUS_AVAILABLE:
            self._init_message_bus(config)
        
        # 初始化诊断提供者
        self._init_diagnostics(config)
        
        logger.info("实时数据发布已启用")
    
    def _push_config_to_redis(self) -> None:
        """推送组态信息到 Redis（供历史数据服务使用）"""
        if self._realtime_publisher is None:
            return
        
        try:
            # 收集实例信息
            instances_info = {}
            stored_params = []
            
            for instance_name, instance in self._instances.items():
                stored_attrs = getattr(instance.__class__, "stored_attributes", [])
                instance_info = {
                    "type": instance.__class__.__name__,
                    "stored_attributes": stored_attrs,
                }
                instances_info[instance_name] = instance_info
                
                # 收集需要存储的参数
                for attr_name in stored_attrs:
                    param_name = f"{instance_name}.{attr_name}"
                    stored_params.append(param_name)
            
            # 添加变量类型的参数
            for item in self._program_items:
                if item.type.upper() == "VARIABLE":
                    stored_params.append(item.name)
            
            # 推送组态信息
            self._realtime_publisher.push_config(
                cycle_time=self.clock.config.cycle_time,
                sample_interval=self.clock.config.sample_interval,
                stored_params=stored_params if stored_params else None,  # None 表示全部存储
                instances_info=instances_info,
            )
            
            logger.info("组态信息已推送到 Redis 和消息总线（供历史数据服务和 OPCUA Server 使用）")
        except Exception as e:
            logger.error(f"Failed to push config to Redis: {e}", exc_info=True)
    
    def _init_message_bus(self, realtime_config: Any) -> None:
        """初始化消息总线（用于接收 OPCUA 写值命令）"""
        if not MESSAGE_BUS_AVAILABLE:
            logger.warning("消息总线不可用，OPCUA 写值功能将不可用")
            return
        
        try:
            # 使用与 RealtimePublisher 相同的配置
            # 如果传入了bus_config，使用它（确保与ServiceManager使用相同的MessageBus实例）
            # 否则创建新的配置，但使用统一的key_prefix
            if realtime_config.bus_config:
                bus_config = realtime_config.bus_config
            else:
                bus_config = BusConfig(
                    redis_host=realtime_config.redis_host,
                    redis_port=realtime_config.redis_port,
                    redis_db=realtime_config.redis_db,
                    redis_password=realtime_config.redis_password,
                    key_prefix="service_manager"  # 使用与ServiceManager相同的key_prefix
                )
            
            self._message_bus = MessageBus(bus_config)
            # 多引擎场景必须使用 engine.<engine_id> 独立服务名，避免命令被错误引擎消费
            service_name = f"engine.{self.engine_id}"
            self._message_server = MessageServer(service_name, self._message_bus)  # 参数顺序：service_name, bus
            self._service_registry = ServiceRegistry(self._message_bus)
            
            # 注册服务
            try:
                self._service_registry.register(
                    service_name,
                    metadata={
                        "version": "1.0.0",
                        "description": f"统一执行引擎 [{self.engine_id}]",
                        "capabilities": ["data_generation", "realtime_execution", "opcua_write_value"],
                        "status": "initialized",
                        "engine_id": self.engine_id
                    }
                )
                logger.info(f"Engine服务 {service_name} 已注册，使用key_prefix: {bus_config.key_prefix}")
                
                # 验证注册是否成功
                registered_services = self._service_registry.list_all()
                logger.info(f"当前已注册的所有服务: {registered_services}")
            except Exception as e:
                logger.error(f"Engine服务注册失败: {e}", exc_info=True)
                raise
            
            # 注册 OPCUA 写值命令处理器
            self._message_server.register_handler("opcua_write_value", self._handle_opcua_write_value)
            
            # 启动消息服务器（MessageServer.start() 内部会创建线程）
            self._message_server.start()
            
            logger.info("消息总线已启用，OPCUA 写值功能可用，服务已注册")
        except Exception as e:
            logger.error(f"消息总线初始化失败: {e}", exc_info=True)
            self._message_bus = None
            self._message_server = None
    
    def _init_diagnostics(self, realtime_config: Any) -> None:
        """初始化诊断提供者"""
        try:
            from controller.diagnostics import EngineDiagnosticProvider
            import redis
            
            # 创建 Redis 客户端（用于诊断）
            redis_client = redis.Redis(
                host=realtime_config.redis_host,
                port=realtime_config.redis_port,
                db=realtime_config.redis_db,
                password=realtime_config.redis_password,
                decode_responses=True,
            )
            
            self._diagnostic_provider = EngineDiagnosticProvider(self, redis_client)
            logger.info("诊断提供者已初始化")
        except ImportError:
            logger.debug("诊断模块不可用，跳过诊断初始化")
        except Exception as e:
            logger.warning(f"诊断提供者初始化失败: {e}", exc_info=True)
    
    def update_diagnostics(self) -> None:
        """更新诊断信息"""
        if self._diagnostic_provider:
            try:
                self._diagnostic_provider.push_diagnostics()
            except Exception as e:
                logger.debug(f"更新诊断信息失败: {e}")
    
    def _handle_opcua_write_value(self, message: Any) -> Dict[str, Any]:
        """
        处理 OPCUA 写值命令
        
        Args:
            message: 消息对象，payload 包含 {"param_name": str, "value": Any}
        
        Returns:
            处理结果
        """
        try:
            # 兼容 MessageBus Server 的 handler(message.payload) 调用方式
            if isinstance(message, dict):
                payload = message
            else:
                payload = getattr(message, "payload", {}) or {}
            param_name = payload.get("param_name")
            value = payload.get("value")
            
            if not param_name:
                return {"success": False, "error": "param_name is required"}
            
            # 对齐前端写值语义：
            # 1) 先按 VARIABLE 全名匹配（支持 namespace.variable）
            # 2) 否则按 instance.attr 处理（使用 rsplit 支持 namespace.instance.attr）
            variable_names = {
                item.name
                for item in self._program_items
                if str(item.type).upper() == "VARIABLE"
            }

            if param_name in variable_names:
                self.queue_variable_update(param_name, new_value=value)
                logger.info(f"OPCUA write variable queued: {param_name} = {value}")
            elif "." in param_name:
                instance_name, param = param_name.rsplit(".", 1)
                if instance_name in self._instances:
                    self.queue_param_update(instance_name, param, value)
                    logger.info(f"OPCUA write instance param queued: {param_name} = {value}")
                else:
                    # 兜底：当实例不存在时尝试按变量名处理（兼容历史写法）
                    self.queue_variable_update(param_name, new_value=value)
                    logger.info(f"OPCUA write fallback variable queued: {param_name} = {value}")
            else:
                self.queue_variable_update(param_name, new_value=value)
                logger.info(f"OPCUA write variable queued: {param_name} = {value}")
            
            # 记录OPCUA写命令到诊断提供者
            if self._diagnostic_provider:
                try:
                    self._diagnostic_provider.record_opcua_write()
                except Exception:
                    pass
            
            return {"success": True, "param_name": param_name, "value": value}
        except Exception as e:
            logger.error(f"Failed to handle OPCUA write value: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # 基本执行 API ------------------------------------------------------
    def run_realtime(self) -> Iterable[Dict[str, Any]]:
        """
        实时模式执行（永久运行，阻塞运行）。
        
        特点：
            - 自动设置 Clock 为 REALTIME 模式（每个周期会 sleep）
            - 永久运行，直到外部中断（KeyboardInterrupt 等）
            - 返回生成器，用于流式处理数据
            - 适合实时模拟、在线运行、与外部系统交互
        
        Returns:
            Iterable[Dict[str, Any]] - 生成器，持续产生快照
        
        示例：
            # 实时运行，与外部系统交互
            try:
                for snapshot in engine.run_realtime():
                    send_to_opcua(snapshot)
                    read_external_input()
            except KeyboardInterrupt:
                print("停止运行")
        """
        # 自动设置 Clock 为 REALTIME 模式；若设置 FAST_TEST=1，则使用 GENERATOR 提速单测
        if os.getenv("FAST_TEST") == "1":
            self.clock.config.mode = ClockMode.GENERATOR
            logger.info("切换到 GENERATOR 模式（FAST_TEST 加速实时运行）")
        else:
            self.clock.config.mode = ClockMode.REALTIME
            logger.info("切换到 REALTIME 模式（实时运行）")
        
        self.clock.start()
        try:
            cycle_count = 0
            while True:
                snapshot = self._step_once()
                cycle_count = snapshot.get("cycle_count", 0)
                
                # 注意：节点执行时间已在 _step_once() 中记录到诊断提供者
                # 这里不再需要测量，因为之前测量的时间包含了 sleep，导致占比计算错误
                
                # 如果启用了实时数据发布，推送到 Redis（每个周期都推送）
                if self._realtime_publisher is not None:
                    try:
                        self._realtime_publisher.push_snapshot(snapshot)
                        # 记录发布到诊断提供者
                        if self._diagnostic_provider:
                            try:
                                self._diagnostic_provider.record_publish()
                            except Exception:
                                pass
                    except Exception as e:
                        logger.error(f"Failed to push snapshot to Redis: {e}", exc_info=True)
                
                # 定期更新服务心跳（每100个周期更新一次）
                if self._service_registry and cycle_count % 100 == 0:
                    service_name = f"engine.{self.engine_id}"
                    try:
                        self._service_registry.update_heartbeat(service_name)
                        self._service_registry.update_health(service_name, "healthy")
                    except Exception:
                        pass
                
                yield snapshot
        finally:
            self.clock.stop()
            # 关闭数据管理模块
            if self._realtime_publisher is not None:
                try:
                    self._realtime_publisher.close()
                except Exception as e:
                    logger.error(f"Failed to close realtime publisher: {e}", exc_info=True)
            
            # 注销服务
            if self._service_registry is not None:
                service_name = f"engine.{self.engine_id}"
                try:
                    self._service_registry.unregister(service_name)
                except Exception as e:
                    logger.error(f"Failed to unregister service {service_name}: {e}", exc_info=True)
            
            # 关闭消息总线
            if self._message_server is not None:
                try:
                    self._message_server.stop()
                except Exception as e:
                    logger.error(f"Failed to stop message server: {e}", exc_info=True)
            
            if self._message_bus is not None:
                try:
                    self._message_bus.close()
                except Exception as e:
                    logger.error(f"Failed to close message bus: {e}", exc_info=True)
    
    def run_generator(self, n: int) -> List[Dict[str, Any]]:
        """
        生成器模式执行（快速批量生成）。
        
        特点：
            - 自动设置 Clock 为 GENERATOR 模式（不 sleep，快速执行）
            - 执行指定周期数，返回所有快照的列表
            - 适合批量数据生成、测试、离线仿真
        
        Args:
            n: 执行周期数（必须 > 0）
        
        Returns:
            List[Dict[str, Any]] - 所有周期的快照列表
        
        示例：
            # 批量生成 10000 个周期的数据
            results = engine.run_generator(10000)
            
            # 保存到文件
            save_to_csv(results, 'output.csv')
        """
        if n <= 0:
            raise ValueError(f"生成器模式必须指定周期数 > 0，got n={n}")
        
        # 自动设置 Clock 为 GENERATOR 模式
        self.clock.config.mode = ClockMode.GENERATOR
        logger.info("切换到 GENERATOR 模式（快速批量生成），执行 %d 个周期", n)
        
        results: List[Dict[str, Any]] = []
        self.clock.start()
        try:
            for _ in range(n):
                snapshot = self._step_once()
                results.append(snapshot)
        finally:
            self.clock.stop()
        return results
    
    def export_to_csv(
        self,
        snapshots: List[Dict[str, Any]],
        template_name: str,
        output_path: str | Path,
        selected_variables: List[str] | None = None,
    ) -> None:
        """
        使用指定模板导出数据到 CSV 文件

        Args:
            snapshots: 快照数据列表（通常来自 run_generator 的返回值）
            template_name: 模板名称（如 moban_1, moban_2）
            output_path: 输出文件路径
            selected_variables: 若提供则只导出这些列（不含元数据键）；None 表示按 ``get_display_variables()``（DSL display_args）筛选列
        """
        try:
            from components.export_templates import TemplateManager
        except ImportError:
            raise ImportError("导出功能需要 export_templates 模块，请确保模块已正确安装")

        template_manager = TemplateManager()
        template = template_manager.load_template(template_name)

        self.export_snapshots(
            snapshots,
            output_path,
            template,
            file_format="csv",
            sheet_name=None,
            selected_variables=selected_variables,
        )

    def export_snapshots(
        self,
        snapshots: List[Dict[str, Any]],
        output_path: str | Path,
        template: Any,
        file_format: str = "csv",
        sheet_name: Optional[str] = None,
        selected_variables: List[str] | None = None,
    ) -> None:
        """
        按内存中的 ExportTemplate 与目标格式导出快照（CSV / xlsx / xls）。

        Args:
            snapshots: 快照列表（通常来自 run_generator）
            output_path: 输出路径（扩展名应与 file_format 一致）
            template: ``ExportTemplate`` 实例
            file_format: ``csv`` | ``xlsx`` | ``xls``
            sheet_name: Excel 工作表名，缺省为「控制器」（仅 xlsx/xls）
            selected_variables: 要导出的列；None 表示由调用方语义决定（run_export 会传入已解析列表）
        """
        try:
            from components.export_templates import CSVExporter, ExcelExporter
        except ImportError as e:
            raise ImportError("导出功能需要 export_templates 模块") from e

        sample_interval = self.config.clock.sample_interval or self.config.clock.cycle_time
        fmt = (file_format or "csv").lower()

        if fmt == "csv":
            exporter = CSVExporter(template, sample_interval=sample_interval)
            exporter.export(snapshots, output_path, column_keys=selected_variables)
            return

        if fmt in ("xlsx", "xls"):
            exporter = ExcelExporter(
                template,
                file_format=fmt,
                sheet_name=sheet_name or "控制器",
                sample_interval=sample_interval,
            )
            exporter.export(snapshots, output_path, column_keys=selected_variables)
            return

        raise ValueError(f"不支持的导出格式: {file_format}")

    # 变更队列与动态管理 -----------------------------------------------
    def queue_param_update(self, instance_name: str, param_name: str, value: Any) -> None:
        """队列化实例参数更新，周期空闲时应用。"""
        with self._lock:
            self._pending_param_updates.append((instance_name, param_name, value))

    def queue_variable_update(
        self, name: str, new_expression: str | None = None, new_value: Any | None = None
    ) -> None:
        """
        队列化变量表达式或当前值更新。

        Args:
            name: 变量名（包含命名空间）
            new_expression: 若提供则更新表达式
            new_value: 若提供则立即写值（当前周期的 value）
        """
        with self._lock:
            self._pending_variable_updates.append((name, new_expression, new_value))

    def queue_add_program(self, item: ProgramItem) -> None:
        """队列化新增 program（算法/模型）。"""
        with self._lock:
            self._pending_add_items.append(item)

    def queue_delete_instance(self, instance_name: str) -> None:
        """队列化删除实例。"""
        with self._lock:
            self._pending_delete_instances.append(instance_name)

    def queue_add_variable(self, item: ProgramItem) -> None:
        """队列化新增 Variable 项。"""
        with self._lock:
            self._pending_add_items.append(item)

    def queue_delete_variable(self, var_name: str) -> None:
        """队列化删除变量。"""
        with self._lock:
            self._pending_delete_variables.append(var_name)

    def load_config(self, config: ProgramConfig, namespace: str = "") -> None:
        """
        动态加载新的 ProgramConfig，并按命名空间合并。

        注意：不考虑兼容性，命名冲突需外部保证或使用 namespace 规避。
        """
        with self._lock:
            ns_items = [self._apply_namespace(item, namespace) for item in config.program]
            self._program_items.extend(ns_items)
            self._rebuild_nodes_from_program_items()
            self._configure_lags_from_items(ns_items, config.lag_requirements, namespace)
            # 推送更新后的组态信息
            self._push_config_to_redis()

    def _apply_namespace(self, item: ProgramItem, namespace: str) -> ProgramItem:
        """为 ProgramItem 添加命名空间前缀，并重写表达式中的名称。"""
        if not namespace:
            return deepcopy(item)
        new_item = deepcopy(item)
        mapping: Dict[str, str] = {item.name: f"{namespace}.{item.name}"}
        new_item.name = mapping[item.name]
        if new_item.expression:
            new_item.expression = self._rewrite_expression_with_mapping(
                new_item.expression, mapping
            )
        return new_item

    def _rewrite_expression_with_mapping(self, expression: str, mapping: Dict[str, str]) -> str:
        """使用 AST 将 Name/Attribute 的名称按映射表替换。"""
        try:
            tree = ast.parse(expression, mode="exec")
        except SyntaxError:
            return expression

        class _Rewriter(ast.NodeTransformer):
            def __init__(self, mapping: Dict[str, str]) -> None:
                self.mapping = mapping

            def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802
                if node.id in self.mapping:
                    return self._build_attr_chain(self.mapping[node.id], node)
                return node

            def visit_Attribute(self, node: ast.Attribute) -> ast.AST:  # noqa: N802
                self.generic_visit(node)
                if isinstance(node.value, ast.Name) and node.value.id in self.mapping:
                    node.value = self._build_attr_chain(self.mapping[node.value.id], node.value)
                return node

            @staticmethod
            def _build_attr_chain(name: str, ref_node: ast.AST) -> ast.AST:
                """
                将 'ns.item' 转换为 Attribute 链，保持位置信息。
                """
                parts = name.split(".")
                if not parts:
                    return ref_node
                base = ast.Name(id=parts[0], ctx=ast.Load())
                ast.copy_location(base, ref_node)
                current: ast.AST = base
                for attr in parts[1:]:
                    attr_node = ast.Attribute(value=current, attr=attr, ctx=ast.Load())
                    ast.copy_location(attr_node, ref_node)
                    current = attr_node
                return current

        tree = _Rewriter(mapping).visit(tree)
        ast.fix_missing_locations(tree)
        try:
            return ast.unparse(tree)  # type: ignore[attr-defined]
        except Exception:
            return expression

    def _rebuild_nodes_from_program_items(self) -> None:
        """按当前 program_items 重建节点与实例列表。"""
        self._nodes = []
        self._expr_nodes = []
        # 重用已有实例；不存在则创建
        for item in self._program_items:
            if item.type.upper() == "VARIABLE":
                expr_config = ExpressionConfig(name=item.name, expression=item.expression)
                node = ExpressionNode(expr_config, self._instances)
                self._expr_nodes.append(node)
                self._nodes.append(node)
            else:
                instance = self._instances.get(item.name)
                if instance is None:
                    instance = self._factory.create_instance(item)
                    self._instances[item.name] = instance
                stored_attrs = getattr(instance.__class__, "stored_attributes", [])
                node = AlgorithmNode(
                    instance=instance,
                    expression=item.expression,
                    stored_attributes=stored_attrs,
                    instance_name=item.name,
                    instances=self._instances,
                )
                self._nodes.append(node)

    def _apply_pending_changes(self) -> None:
        """在周期空闲时应用所有队列变更。"""
        with self._lock:
            if (
                not self._pending_param_updates
                and not self._pending_variable_updates
                and not self._pending_add_items
                and not self._pending_delete_instances
                and not self._pending_delete_variables
            ):
                return

            # 删除变量
            for var_name in self._pending_delete_variables:
                self.vars.delete(var_name)
                self._program_items = [p for p in self._program_items if p.name != var_name]
                self._nodes = [n for n in self._nodes if not isinstance(n, ExpressionNode) or n.name != var_name]
            self._pending_delete_variables.clear()

            # 删除实例
            for inst_name in self._pending_delete_instances:
                self._instances.pop(inst_name, None)
                self._program_items = [p for p in self._program_items if p.name != inst_name]
                self._nodes = [
                    n
                    for n in self._nodes
                    if not (isinstance(n, AlgorithmNode) and getattr(n, "_instance_name", "") == inst_name)
                ]
            self._pending_delete_instances.clear()

            # 新增 program / variable
            if self._pending_add_items:
                self._program_items.extend(self._pending_add_items)
                self._pending_add_items.clear()

            # 重建节点（保证顺序与依赖一致性）
            self._rebuild_nodes_from_program_items()
            
            # 推送更新后的组态信息
            self._push_config_to_redis()

            # 参数更新
            for inst_name, param, value in self._pending_param_updates:
                inst = self._instances.get(inst_name)
                if inst is not None:
                    setattr(inst, param, value)
            self._pending_param_updates.clear()

            # 变量更新
            for var_name, new_expr, new_val in self._pending_variable_updates:
                # 更新表达式节点配置
                for node in self._nodes:
                    if isinstance(node, ExpressionNode) and node.name == var_name and new_expr is not None:
                        node.config.expression = new_expr
                        break
                if new_val is not None:
                    self.vars.set(var_name, new_val)
            self._pending_variable_updates.clear()

    def _configure_lags_from_items(
        self, items: List[ProgramItem], lag_requirements: Dict[str, int], namespace: str
    ) -> None:
        """根据 lag 需求配置历史长度。"""
        for name, steps in lag_requirements.items():
            full_name = f"{namespace}.{name}" if namespace else name
            safe_steps = int(steps * LAG_SAFETY_MARGIN)
            self.vars.configure_lag(full_name, safe_steps)

    def _precompile_nodes(self) -> None:
        """
        预编译所有节点以提升性能。
        
        为ExpressionNode和AlgorithmNode启用表达式预编译缓存。
        """
        for node in self._nodes:
            if isinstance(node, ExpressionNode):
                # 如果节点尚未预编译，进行预编译
                if not hasattr(node, '_evaluator') or node._evaluator is None:
                    node._precompile(self.vars)
            elif isinstance(node, AlgorithmNode):
                # 如果节点尚未预编译，进行预编译
                if not hasattr(node, '_evaluator') or node._evaluator is None:
                    node._evaluator = ExpressionEvaluator(self.vars, self._instances)
                    # 预编译所有参数表达式
                    for param_name, param_expr in node._parsed_args.items():
                        try:
                            node._evaluator.evaluate(param_expr)
                        except Exception:
                            pass

    def _analyze_lag_for_expression(self, expr: str) -> Dict[str, int]:
        """简单分析表达式中的 lag 需求（运行时新增变量时使用）。"""
        result: Dict[str, int] = {}
        try:
            tree = ast.parse(expr, mode="exec")
        except SyntaxError:
            return result

        class _LagVisitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.local: Dict[str, int] = {}

            def visit_Subscript(self, node: ast.Subscript) -> None:  # noqa: N802
                steps = self._parse_steps(node.slice)
                target = self._extract_name(node.value)
                if steps > 0 and target:
                    prev = self.local.get(target, 0)
                    if steps > prev:
                        self.local[target] = steps
                self.generic_visit(node)

            def _parse_steps(self, slice_node: ast.AST) -> int:
                if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, (int, float)):
                    return abs(int(slice_node.value))
                if isinstance(slice_node, ast.UnaryOp) and isinstance(slice_node.operand, ast.Constant):
                    if isinstance(slice_node.operand.value, (int, float)):
                        return abs(int(slice_node.operand.value))
                return 0

            def _extract_name(self, node: ast.AST) -> str:
                if isinstance(node, ast.Name):
                    return node.id
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    return f"{node.value.id}.{node.attr}"
                return ""

        visitor = _LagVisitor()
        visitor.visit(tree)
        return visitor.local

    def _step_once(self) -> Dict[str, Any]:
        """
        执行一个周期（内部方法）。

        执行顺序：
        1. 使用当前 `sim_time` 计算本周期的目标时间标签 `t`
        2. 执行所有表达式节点（算法计算）
        3. 调用 `clock.step()`，在内部根据模式决定是否 sleep，并更新周期计数

        Returns:
            当前周期完成后所有变量的快照，包含：
            - 所有变量的当前值
            - cycle_count: 周期计数
            - need_sample: 是否需要采样
            - time_str: 当前时间字符串
            - sim_time: 当前模拟时间（浮点数，秒）
        """
        # 性能优化：在 GENERATOR 模式下禁用 debug 日志（避免日志I/O成为性能瓶颈）
        # 只在 REALTIME 模式下记录 debug 日志
        if self.config.clock.mode == ClockMode.REALTIME:
            logger.debug(
                "执行周期 %d，sim_time=%.3f，节点数=%d",
                self.clock.cycle_count,
                self.clock.sim_time,
                len(self._nodes),
            )
        
        # 应用排队变更
        self._apply_pending_changes()

        # 1. 计算本周期的目标时间标签（下一个采样点）
        t = self.clock.sim_time + self.config.clock.cycle_time

        # 2. 按顺序执行所有节点（记录节点执行时间，不包括 sleep）
        node_execution_start = time.time()
        # 先执行算法节点，再执行表达式节点
        for node in self._nodes:
            try:
                if isinstance(node, AlgorithmNode):
                    node.step(self.vars)
                elif isinstance(node, ExpressionNode):
                    node.step(self.vars)
            except Exception as e:
                logger.error(
                    "节点执行失败: node=%s, error=%s",
                    node.name if hasattr(node, 'name') else type(node).__name__,
                    e,
                    exc_info=True,
                )
                # 不抛出异常，继续执行其他节点，避免整个循环停止
                # 但记录错误以便调试
                continue
        
        # 计算节点执行时间（不包括 sleep）
        node_execution_time = time.time() - node_execution_start
        
        # 记录节点执行时间到诊断提供者（在 clock.step() 之前，避免包含 sleep）
        if self._diagnostic_provider:
            try:
                self._diagnostic_provider.record_execution_time(node_execution_time)
            except Exception as e:
                logger.debug(f"Failed to record execution time: {e}")

        # 3. 步进时钟（内部根据模式决定是否 sleep，并记录执行时间）
        cycle_count, need_sample, time_str, exec_ratio = self.clock.step()

        # 4. 返回快照（确保包含所有应该存在的变量）
        snapshot = self._build_complete_snapshot()
        snapshot["cycle_count"] = cycle_count
        snapshot["need_sample"] = need_sample
        snapshot["time_str"] = time_str
        snapshot["sim_time"] = t
        snapshot["exec_ratio"] = exec_ratio
        return snapshot
    
    def _build_complete_snapshot(self) -> Dict[str, Any]:
        """
        构建完整的快照，包含所有应该存在的变量（即使还没有值）。
        
        包括：
        1. VariableStore 中已有的变量
        2. 所有 Variable 类型的变量（从 program_items 中获取）
        3. 所有实例的存储属性（从 instances 中获取）
        """
        snapshot = self.vars.snapshot()
        
        # 添加所有 Variable 类型的变量（如果还没有值，使用默认值 0.0）
        for item in self._program_items:
            if item.type.upper() == "VARIABLE":
                if item.name not in snapshot:
                    snapshot[item.name] = 0.0
        
        # 添加所有实例的存储属性（如果还没有值，从实例获取或使用默认值 0.0）
        for instance_name, instance in self._instances.items():
            stored_attrs = getattr(instance.__class__, "stored_attributes", [])
            for attr_name in stored_attrs:
                var_key = f"{instance_name}.{attr_name}"
                if var_key not in snapshot:
                    # 尝试从实例获取当前值
                    if hasattr(instance, attr_name):
                        try:
                            value = getattr(instance, attr_name)
                            snapshot[var_key] = float(value) if value is not None else 0.0
                        except Exception:
                            snapshot[var_key] = 0.0
                    else:
                        snapshot[var_key] = 0.0
        
        return snapshot

    def get_variable_meta(self) -> Dict[str, Any]:
        """
        构建当前组态下所有可导出/可绘制的位号元信息。

        - VARIABLE 类型：键为变量名本身。
        - 算法/模型实例：键为 ``instance.attr``。

        is_display / plot_scale_ref 由 DSL 的 display_args（解析为 display_specs）决定；未写 display_args 则不展示。
        """
        meta: Dict[str, Any] = {}
        for item in self._program_items:
            ptype = item.type.upper()
            if ptype == "VARIABLE":
                ref = DEFAULT_PLOT_SCALE_REF
                is_disp = False
                if item.display_specs is not None and len(item.display_specs) > 0:
                    for an, r in item.display_specs:
                        if an == item.name:
                            is_disp = True
                            ref = r
                            break
                meta[item.name] = {
                    "instance": item.name,
                    "param": "",
                    "description": "用户自定义变量",
                    "is_display": is_disp,
                    "plot_scale_ref": ref,
                }
                continue

            instance = self._instances.get(item.name)
            if instance is None:
                continue
            cls = instance.__class__
            stored_attrs = getattr(cls, "stored_attributes", []) or []
            descriptions = getattr(cls, "param_descriptions", {}) or {}
            stored_set = set(stored_attrs)

            display_attr_set: set = set()
            scale_by_attr: Dict[str, float] = {}
            if item.display_specs is not None and len(item.display_specs) > 0:
                for attr_name, ref in item.display_specs:
                    if attr_name not in stored_set:
                        logger.warning(
                            "display_args 属性不在 stored_attributes 中，已忽略: %s.%s",
                            item.name,
                            attr_name,
                        )
                        continue
                    display_attr_set.add(attr_name)
                    scale_by_attr[attr_name] = ref

            for attr_name in stored_attrs:
                key = f"{item.name}.{attr_name}"
                is_d = attr_name in display_attr_set
                pref = scale_by_attr.get(attr_name, DEFAULT_PLOT_SCALE_REF)
                meta[key] = {
                    "instance": item.name,
                    "param": attr_name,
                    "description": descriptions.get(attr_name, attr_name),
                    "is_display": is_d,
                    "plot_scale_ref": pref,
                }
        return meta

    def get_display_variables(self) -> List[str]:
        """
        默认用于前端绘图/导出的位号列表。

        仅当 YAML 写了非空 ``display_args`` 时，对应变量或实例属性才会列入；未写 ``display_args`` 或
        ``display_args: []`` 均不进入本列表。
        """
        ordered: List[str] = []
        for item in self._program_items:
            ptype = item.type.upper()
            if ptype == "VARIABLE":
                if item.display_specs and len(item.display_specs) > 0:
                    ordered.append(item.name)
                continue
            instance = self._instances.get(item.name)
            if instance is None:
                continue
            cls = instance.__class__
            stored_attrs = getattr(cls, "stored_attributes", []) or []
            stored_set = set(stored_attrs)
            if not item.display_specs or len(item.display_specs) == 0:
                continue
            for attr_name, _ in item.display_specs:
                if attr_name in stored_set:
                    ordered.append(f"{item.name}.{attr_name}")
        return ordered

    def get_plot_scales(self) -> Dict[str, float]:
        """每位号对应的绘图满量程参考 ref（仅影响前端曲线，y_plot = y_raw * 100/ref）。"""
        scales: Dict[str, float] = {}
        for key, info in self.get_variable_meta().items():
            scales[key] = float(info.get("plot_scale_ref", DEFAULT_PLOT_SCALE_REF))
        return scales

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息供诊断使用"""
        return {
            "cycle_count": self.clock.cycle_count,
            "sim_time": round(self.clock.sim_time, 3),
            "node_count": len(self._nodes),
            "variable_count": len(self.vars._variables),
            "instance_count": len(self._instances),
            "mode": self.clock.config.mode.name
        }

class TaskRuntime:
    """
    任务运行时 (TaskRuntime)
    
    用于执行特定的、有时限的任务，如：
    - 快速批量生成数据 (sleep_time=0)
    - JIT 孵化计算逻辑
    - 独立沙箱运行
    """
    def __init__(self, engine: UnifiedEngine):
        self.engine = engine

    def run_sync(self, steps: int) -> List[Dict[str, Any]]:
        """
        同步运行指定步数，不进行任何等待
        """
        # 强制切换到 GENERATOR 模式
        original_mode = self.engine.clock.config.mode
        self.engine.clock.config.mode = ClockMode.GENERATOR
        
        results = []
        try:
            for _ in range(steps):
                snapshot = self.engine._step_once()
                results.append(snapshot)
        finally:
            self.engine.clock.config.mode = original_mode
            
        return results


