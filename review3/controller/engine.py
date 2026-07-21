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


logger = get_logger()


# 连续失败多少次后切入 SAFE STATE（算法节点持续抛异常时触发）
_SAFE_STATE_FAILURE_THRESHOLD = 5

# 原子在线写：默认可写属性（MV 另受 MODE 约束）
_ATOMIC_WRITE_ATTRS = frozenset({"SV", "PB", "TI", "TD", "KD"})
_ATOMIC_WRITE_MV_ATTR = "MV"
# 与 components.programs.pid 手动类 MODE 对齐
_ATOMIC_MV_ALLOWED_MODES = frozenset({2, 3, 4, 8})
_ATOMIC_REJECT_ATTRS = frozenset({
    "PV", "AUTO", "CAS", "level", "current_opening",
    "inlet_flow", "outlet_flow", "source_flow",
})


@dataclass(frozen=True)
class AtomicWrite:
    """单条原子写目标（tag 为完整位号，如 pid2.SV）。"""

    tag: str
    value: float


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

        # 引擎 ID（用于标识不同引擎实例）
        self.engine_id: str = "default"

        # 实时数据发布器（默认未启用；诊断模块依赖 hasattr 检查）
        self._realtime_publisher: Any | None = None
        self._realtime_enabled: bool = False

        # 外部覆写值队列（来自 OPCUA 等外部系统的写值命令，在每个周期开始时应用）
        self._external_overrides: List[Tuple[str, float]] = []

        # 原子批次队列：每项为已校验的 (instance_name, attr, value) 列表；整批同周期应用
        self._pending_atomic_batches: List[List[Tuple[str, str, float]]] = []

        # 节点异常连续失败计数 & SAFE STATE 标志
        # 工业语义：算法节点持续抛异常时不应"继续算错误的值"，而是切到 SAFE STATE
        # 让外部系统（如 OPCUA 客户端）能感知到控制器已暂停，避免基于错误数据做决策。
        # 一旦进入 SAFE STATE 不会自动恢复，必须人工重启引擎。
        self._consecutive_failures: int = 0
        self._safe_state: bool = False

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
        启用实时数据发布（已禁用 — standalone 模式不再支持 Redis/消息总线）。

        历史说明：distributed 模式下此方法会创建 ``RealtimePublisher`` 连接 Redis、
        通过消息总线发布事件，供其他 OPCUA Server / StorageService 订阅。
        standalone 版本已删除上述模块（``realtime_publisher`` /
        ``playback_engine``），本方法保留仅为接口兼容：调用后仅记录警告，
        不会真正建立任何外部连接，也不会抛异常中断调用方。

        如需让外部系统消费引擎数据，请通过 ``datacenter/opcua_server.py``
        启动 OPCUA Server（``standalone_main.py`` 默认会自动启动），
        数据走内存总线，不依赖任何中间件。

        Args:
            config: 实时数据配置（已忽略，保留仅为接口兼容）。
            enable_message_bus: 是否启用消息总线（已忽略）。
        """
        if self._realtime_enabled:
            return
        logger.warning(
            "enable_realtime_data 已禁用：standalone 模式不再支持 Redis/消息总线。"
            "外部数据消费请使用 OPCUA Server（standalone_main.py 已自动启动）。"
        )
        # 标记为已启用（实际上是 no-op），避免重复调用时反复打印 warning
        self._realtime_publisher = None
        self._realtime_enabled = True

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
                yield snapshot
        finally:
            self.clock.stop()
    
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

    def queue_atomic_writes(self, writes: List[AtomicWrite]) -> None:
        """整批校验并入队；任一非法则抛 ValueError，且零部分入队。"""
        if not writes:
            raise ValueError("atomic writes batch must not be empty")
        parsed: List[Tuple[str, str, float]] = []
        seen_tags: set[str] = set()
        with self._lock:
            for item in writes:
                tag = str(item.tag).strip()
                value = item.value
                if tag in seen_tags:
                    raise ValueError(f"duplicate tag in batch: {tag}")
                seen_tags.add(tag)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise ValueError(f"non-numeric value for tag {tag}")
                fval = float(value)
                if fval != fval or fval in (float("inf"), float("-inf")):
                    raise ValueError(f"non-finite value for tag {tag}")
                if "." not in tag:
                    raise ValueError(f"unknown or derived tag rejected: {tag}")
                inst_name, attr = tag.rsplit(".", 1)
                if attr in _ATOMIC_REJECT_ATTRS or attr.upper() in {"AUTO", "CAS", "PV"}:
                    raise ValueError(f"readonly or derived tag rejected: {tag}")
                if attr == _ATOMIC_WRITE_MV_ATTR:
                    inst = self._instances.get(inst_name)
                    if inst is None:
                        raise ValueError(f"unknown tag: {tag}")
                    mode = getattr(inst, "MODE", None)
                    try:
                        mode_i = int(mode)
                    except (TypeError, ValueError):
                        raise ValueError(f"MV write rejected: invalid MODE on {inst_name}")
                    if mode_i not in _ATOMIC_MV_ALLOWED_MODES:
                        raise ValueError(
                            f"MV write rejected under MODE={mode_i} (manual modes only)"
                        )
                elif attr not in _ATOMIC_WRITE_ATTRS:
                    # 拒绝未知属性与现场过程量（level / opening / flow 等）
                    raise ValueError(f"unknown or forbidden tag: {tag}")
                inst = self._instances.get(inst_name)
                if inst is None or not hasattr(inst, attr):
                    raise ValueError(f"unknown tag: {tag}")
                parsed.append((inst_name, attr, fval))
            self._pending_atomic_batches.append(parsed)

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
            self._precompile_nodes()
            self._configure_lags_from_items(ns_items, config.lag_requirements, namespace)

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
                and not self._pending_atomic_batches
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

            # 记录新增项（用于增量预编译与 lag 配置）
            new_added: List[ProgramItem] = []
            if self._pending_add_items:
                new_added = list(self._pending_add_items)
                self._program_items.extend(new_added)
                self._pending_add_items.clear()

            # 重建节点（保证顺序与依赖一致性）
            self._rebuild_nodes_from_program_items()

            # Bug B：重建节点后立刻预编译，避免 AlgorithmNode.step 反复重建 evaluator
            self._precompile_nodes()

            # M1：为新增变量/实例属性的 lag 访问预分配历史缓冲区
            if new_added:
                self._configure_lags_for_new_items(new_added)

            # 参数更新
            for inst_name, param, value in self._pending_param_updates:
                inst = self._instances.get(inst_name)
                if inst is not None:
                    setattr(inst, param, value)
            self._pending_param_updates.clear()

            # 原子批次：同一把锁内整批应用，保证同周期 snapshot 可见全部目标
            for batch in self._pending_atomic_batches:
                for inst_name, attr, value in batch:
                    inst = self._instances.get(inst_name)
                    if inst is None:
                        continue
                    setattr(inst, attr, value)
                    self.vars.set(f"{inst_name}.{attr}", value)
            self._pending_atomic_batches.clear()

            # 变量更新
            for var_name, new_expr, new_val in self._pending_variable_updates:
                # Bug D：改表达式必须同时重置预编译缓存，否则 _evaluator / _expr_str
                # 仍指向旧表达式，新表达式永远不会执行。
                for node in self._nodes:
                    if isinstance(node, ExpressionNode) and node.name == var_name and new_expr is not None:
                        node.config.expression = new_expr
                        # 重置 _expr_str 与 _evaluator，下一次 step 触发重新预编译
                        node._expr_str = None
                        node._evaluator = None
                        # 立即预编译，避免下一个周期首次执行时走未优化的 fallback
                        try:
                            node._precompile(self.vars)
                        except Exception as e:
                            logger.warning(
                                "重置变量表达式后预编译失败: var=%s, expr=%s, err=%s",
                                var_name,
                                new_expr,
                                e,
                            )
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
                """
                沿 ``Attribute.value`` 链向上爬到 ``Name``，拼成 dotted 字符串。
                支持任意深度（v1 / pid1.mv / ns1.pid1.mv），无法解析时返回空串。
                """
                parts: list[str] = []
                while isinstance(node, ast.Attribute):
                    parts.insert(0, node.attr)
                    node = node.value
                if isinstance(node, ast.Name):
                    parts.insert(0, node.id)
                    return ".".join(parts)
                return ""

        visitor = _LagVisitor()
        visitor.visit(tree)
        return visitor.local

    def _configure_lags_for_new_items(self, items: List[ProgramItem]) -> None:
        """
        为运行时新增 program / variable 配置 lag 历史缓冲区。

        否则新变量被 [-N] 访问时会因历史缓冲区不存在而返回默认值 0。
        """
        for item in items:
            expr = item.expression or ""
            if not expr:
                continue
            lag_reqs = self._analyze_lag_for_expression(expr)
            for var_name, steps in lag_reqs.items():
                safe_steps = int(steps * LAG_SAFETY_MARGIN)
                self.vars.configure_lag(var_name, safe_steps)
                logger.debug(
                    "运行时 lag 配置: var=%s, max_lag_steps=%d (需求=%d)",
                    var_name,
                    safe_steps,
                    steps,
                )

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

        # 0. 应用外部覆写值（来自 OPCUA 等外部系统的写值命令）
        self._apply_external_overrides()

        # 1. 计算本周期的目标时间标签（下一个采样点）
        t = self.clock.sim_time + self.config.clock.cycle_time

        # 2. 按顺序执行所有节点（记录节点执行时间，不包括 sleep）
        node_execution_start = time.time()
        had_any_failure = False
        if self._safe_state:
            # SAFE STATE 下跳过所有算法/表达式执行，vars 保持上次值
            logger.debug("UnifiedEngine 处于 SAFE STATE，跳过本周期节点执行")
        else:
            # 先执行算法节点，再执行表达式节点
            for node in self._nodes:
                try:
                    if isinstance(node, AlgorithmNode):
                        node.step(self.vars)
                    elif isinstance(node, ExpressionNode):
                        node.step(self.vars)
                except Exception as e:
                    had_any_failure = True
                    self._consecutive_failures += 1
                    node_name = node.name if hasattr(node, "name") else type(node).__name__
                    logger.error(
                        "节点执行失败: node=%s, error=%s, consecutive_failures=%d",
                        node_name,
                        e,
                        self._consecutive_failures,
                        exc_info=True,
                    )
                    # 连续失败达到阈值则切入 SAFE STATE，避免后续周期持续输出错误数据
                    if self._consecutive_failures >= _SAFE_STATE_FAILURE_THRESHOLD:
                        self._safe_state = True
                        logger.critical(
                            "UnifiedEngine 进入 SAFE STATE: 连续 %d 个周期出现节点异常，"
                            "已暂停所有算法执行，需人工重启引擎。last_node=%s, last_error=%s",
                            self._consecutive_failures,
                            node_name,
                            e,
                        )
                        # 后续节点本周期不再尝试
                        break

        # 一整轮所有节点都成功才清零失败计数（部分失败不清零）
        # 进入 SAFE STATE 后不再清零（让 snapshot 里能看到失败累计的最终值）
        if not had_any_failure and not self._safe_state:
            self._consecutive_failures = 0
        
        # 计算节点执行时间（不包括 sleep）
        node_execution_time = time.time() - node_execution_start

        # 3. 步进时钟（内部根据模式决定是否 sleep，并记录执行时间）
        cycle_count, need_sample, time_str, exec_ratio = self.clock.step()

        # 4. 返回快照（确保包含所有应该存在的变量）
        snapshot = self._build_complete_snapshot()
        snapshot["cycle_count"] = cycle_count
        snapshot["need_sample"] = need_sample
        snapshot["time_str"] = time_str
        snapshot["sim_time"] = t
        snapshot["exec_ratio"] = exec_ratio
        # 暴露 SAFE STATE 状态：OPC UA 客户端读到 _safe_state=True 时应停止基于该引擎做控制
        snapshot["_safe_state"] = self._safe_state
        snapshot["_consecutive_failures"] = self._consecutive_failures
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
            "variable_count": len(self.vars._vars),
            "instance_count": len(self._instances),
            "mode": self.clock.config.mode.name
        }

    def step(self) -> Dict[str, Any]:
        """
        执行一个周期并返回快照（公共接口）。

        注意：此方法仅执行计算，不包含 sleep。
        如需实时模式的 sleep，请使用 run_realtime() 或自行在外部调用 clock.step()。

        Returns:
            当前周期完成后所有变量的快照
        """
        return self._step_once()

    def override_variable(self, param_name: str, value: float) -> None:
        """
        接收外部覆写值（来自 OPCUA 等外部系统的写值命令）。

        覆写值会在每个周期开始时应用，优先于该周期的计算结果。

        Args:
            param_name: 参数名（支持 variable_name 或 instance.attribute 格式）
            value: 覆写值
        """
        with self._lock:
            self._external_overrides.append((param_name, value))

    def _apply_external_overrides(self) -> None:
        """
        应用所有外部覆写值（每个周期开始时调用）。

        覆写规则：
        - 对于 VARIABLE 类型：直接写入 VariableStore
        - 对于 instance.attribute：查找实例属性并覆盖
        """
        if not self._external_overrides:
            return

        with self._lock:
            overrides = self._external_overrides
            self._external_overrides = []

        for param_name, value in overrides:
            # 判断是 instance.attribute 还是 VARIABLE
            # 优先尝试 instance.attribute 解析（处理 v_name.SV 等实例属性），
            # 若实例不存在则回退为 VARIABLE 写入（处理带命名空间的变量如 ns1.sin1）。
            handled = False
            if "." in param_name:
                instance_name, attr_name = param_name.rsplit(".", 1)
                instance = self._instances.get(instance_name)
                if instance is not None and hasattr(instance, attr_name):
                    setattr(instance, attr_name, value)
                    # 同时更新 VariableStore
                    var_key = f"{instance_name}.{attr_name}"
                    self.vars.set(var_key, value)
                    handled = True
            if not handled:
                # variable 格式（含带命名空间的 VARIABLE，如 ns1.sin1）
                self.vars.set(param_name, value)


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

    def override_variable(self, param_name: str, value: float) -> None:
        """委托给 engine 处理外部覆写值。"""
        self.engine.override_variable(param_name, value)

    def _apply_external_overrides(self) -> None:
        """委托给 engine 应用外部覆写值。"""
        self.engine._apply_external_overrides()


