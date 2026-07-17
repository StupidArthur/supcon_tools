"""
DSL 解析器

负责：
- 从 YAML 文件中读取 DSL 配置（例如 config/dsl_demo1.yaml）
- 解析出 ProgramItem / ProgramConfig
- 分析哪些变量/属性存在 `[-N]` 访问需求（lag_requirements）

注意：
- 本模块暂时只做配置解析，不直接驱动执行引擎。
- 之后 UnifiedEngine 可以基于 ProgramConfig 构建具体的节点与实例。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Set

import ast
import pathlib

import yaml

from .clock import ClockConfig, ClockMode, LAG_SAFETY_MARGIN, MIN_RECORD_LENGTH
from components.utils.logger import get_logger

logger = get_logger()

# 数据模拟默认绘图缩放：y_plot = y_raw * (DEFAULT_PLOT_SCALE_REF / ref)；ref 缺省为 100 时等价于不缩放
DEFAULT_PLOT_SCALE_REF = 100.0

# display_args 单项：attr 或 attr[ref]，ref 为正数；兼容 PID 的 MV 等大写属性名
_DISPLAY_ARG_TOKEN_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)(?:\[([\d.]+)\])?$",
)


@dataclass
class ProgramItem:
    """
    单条 program 配置。

    Attributes:
        name: 实例名称或变量名称（如 "pid1"、"tank1"、"non_sense_3"）。
        type: 类型字符串（如 "PID"、"CYLINDRICAL_TANK"、"Variable"）。
        init_args: 初始化参数字典（可为空）。
        expression: 表达式字符串（方法调用或赋值表达式）。
        display_specs: 解析自 display_args；每项为 (属性短名, 绘图满量程参考 ref)。
            None 表示未写 display_args：该 program 项不参与默认绘图/默认导出列。
            [] 表示显式为空列表：同上，不展示任何列。
    """

    name: str
    type: str
    expression: str
    init_args: Dict[str, Any]
    display_specs: Optional[List[Tuple[str, float]]] = None
    inputs: Optional[Dict[str, str]] = None
    execute_first: bool = False


@dataclass
class ProgramConfig:
    """
    整体 DSL 配置对象。

    Attributes:
        clock: 时钟配置（只包含本 DSL 关心的字段）。
        program: program 列表（顺序即原始 DSL 中的顺序）。
        record_length: 历史记录长度（用于被 [-N] 访问的变量/属性）。
        lag_requirements: 需要历史数据的变量/属性及其最大 lag 步数。
        export_template: 导出模板配置（可选）。
    """

    clock: ClockConfig
    program: List[ProgramItem]
    record_length: int
    lag_requirements: Dict[str, int]
    export_template: Dict[str, Any] | None = None


class DSLParser:
    """
    DSL 配置解析器。

    当前版本：
    - 只解析一个 YAML 文件，返回 ProgramConfig。
    - 支持：
      - 顶层键：cycle_time, start_time, sample_interval, time_format, record_length
      - program: 列表，每项包含 name, type, init_args(可选), expression
      - 表达式中的 `[-N]` 语法（如 v1[-30], pid1.mv[-10]），用于分析 lag_requirements
    """

    def parse(self, dsl_content: str) -> ProgramConfig:
        """
        从 YAML 字符串解析 ProgramConfig。

        Args:
            dsl_content: YAML 格式的 DSL 配置字符串。

        Returns:
            ProgramConfig 对象
        """
        data = yaml.safe_load(dsl_content) or {}

        # 复用 parse_file 的解析逻辑（不重新读盘）
        return self._parse_loaded_data(data)

    def _parse_loaded_data(self, data: Dict[str, Any]) -> ProgramConfig:
        """
        把已经加载的 YAML dict 解析成 ProgramConfig。

        Args:
            data: 已反序列化的 YAML 数据。
        """
        # 1. 解析 clock 配置
        clock_config = self._parse_clock_config(data)

        # 2. 解析 program 列表
        program_items = self._parse_program_items(data)

        # 2.5 拓扑排序（根据 inputs 依赖关系自动排执行顺序）
        program_items = self._topological_sort(program_items)

        # 3. 分析 lag 需求
        lag_requirements = self._analyze_lag_requirements(program_items)

        # 4. 根据 lag 需求计算 record_length
        if "record_length" in data:
            record_length = int(data.get("record_length"))
        else:
            max_lag = max(lag_requirements.values()) if lag_requirements else 0
            if max_lag > 0:
                record_length = int(max_lag * LAG_SAFETY_MARGIN)
                if record_length < MIN_RECORD_LENGTH:
                    record_length = MIN_RECORD_LENGTH
            else:
                record_length = MIN_RECORD_LENGTH

        # 5. 解析导出模板配置（可选）
        export_template = data.get("export_template")

        return ProgramConfig(
            clock=clock_config,
            program=program_items,
            record_length=record_length,
            lag_requirements=lag_requirements,
            export_template=export_template,
        )

    def parse_file(self, path: str | pathlib.Path) -> ProgramConfig:
        """
        从 YAML 文件解析 ProgramConfig。

        Args:
            path: 配置文件路径。
        """
        path_obj = pathlib.Path(path)
        with path_obj.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return self._parse_loaded_data(data)

    # ------------------------------------------------------------------#
    # 内部解析工具
    # ------------------------------------------------------------------#
    def _parse_clock_config(self, data: Dict[str, Any]) -> ClockConfig:
        """
        从顶层配置解析时钟配置。

        支持两种格式：
        1. 顶层直接指定：cycle_time, start_time, sample_interval, time_format, mode
        2. clock: 嵌套指定：clock.cycle_time, clock.start_time, etc.

        - cycle_time: float，默认 0.5
        - start_time: float 或 ISO 字符串（交给 ClockConfig 自己处理）
        - sample_interval: float，可选
        - time_format: str，可选
        - mode: str，"REALTIME" 或 "GENERATOR"，默认 GENERATOR
        """
        # 优先使用 clock: 嵌套配置，否则使用顶层配置
        clock_data = data.get("clock", data)

        cycle_time = float(clock_data.get("cycle_time", data.get("cycle_time", 0.5)))
        start_time = clock_data.get("start_time", data.get("start_time", 0.0))
        sample_interval = clock_data.get("sample_interval", data.get("sample_interval"))
        time_format = clock_data.get("time_format", data.get("time_format"))

        # 解析 mode
        mode_str = clock_data.get("mode", data.get("mode", "GENERATOR")).upper()
        if mode_str == "REALTIME":
            mode = ClockMode.REALTIME
        else:
            mode = ClockMode.GENERATOR

        return ClockConfig(
            cycle_time=cycle_time,
            start_time=start_time,
            mode=mode,
            sample_interval=sample_interval,
            time_format=time_format,
        )

    def _parse_program_items(self, data: Dict[str, Any]) -> List[ProgramItem]:
        """解析 program 列表。

        支持两种语法：
        - 旧语法：``expression: valve_1.execute(target_opening=v_name.MV)``
        - 新语法：``inputs: {target_opening: v_name.MV}`` + ``params: {full_travel_time: 10}``

        新增类型 Variable / Expression / Lag 会映射为内部 VARIABLE 类型。
        """
        items_raw = data.get("program", []) or []
        program_items: List[ProgramItem] = []

        for item in items_raw:
            name = str(item["name"])
            type_str = str(item["type"])
            type_upper = type_str.upper()

            # params 优先，init_args 向后兼容
            init_args = dict(item.get("params", item.get("init_args", {})) or {})

            # 结构化 inputs（新语法）
            inputs: Optional[Dict[str, str]] = None
            if "inputs" in item and item["inputs"] is not None:
                inputs = {str(k): str(v) for k, v in item["inputs"].items()}

            # execute_first 标记（拓扑排序断环用）
            execute_first = bool(item.get("execute_first", False))

            # 生成或读取表达式
            expr = str(item.get("expression", "")).strip()
            if not expr:
                expr = self._generate_expression(name, type_str, item, inputs)

            # Variable / Expression / Lag 映射为内部 VARIABLE 类型
            if type_upper in ("VARIABLE", "EXPRESSION", "LAG"):
                internal_type = "VARIABLE"
            else:
                internal_type = type_str

            display_specs: Optional[List[Tuple[str, float]]] = None
            if "display_args" in item:
                display_specs = self._parse_display_args_list(name, internal_type, item.get("display_args"))

            program_items.append(
                ProgramItem(
                    name=name,
                    type=internal_type,
                    expression=expr,
                    init_args=init_args,
                    display_specs=display_specs,
                    inputs=inputs,
                    execute_first=execute_first,
                )
            )

        return program_items

    def _generate_expression(
        self,
        name: str,
        type_str: str,
        item: Dict[str, Any],
        inputs: Optional[Dict[str, str]],
    ) -> str:
        """从结构化字段生成表达式字符串（新语法无 expression 字段时调用）。"""
        type_upper = type_str.upper()

        if type_upper == "VARIABLE":
            value = item.get("value", 0.0)
            return f"{name} = {value}"

        if type_upper == "EXPRESSION":
            formula = str(item.get("formula", "0")).strip()
            return f"{name} = {formula}"

        if type_upper == "LAG":
            source = str(item.get("source", "")).strip()
            delay = int(item.get("delay", 1))
            if source:
                return f"{name} = {source}[-{delay}]"
            return f"{name} = 0"

        # 算法/模型类型：从 inputs 拼接 execute() 调用
        if inputs:
            params_str = ", ".join(f"{k}={v}" for k, v in inputs.items())
            return f"{name}.execute({params_str})"

        # 无 inputs 的算法/模型（如 SINE_WAVE）
        return f"{name}.execute()"

    def _parse_display_args_list(
        self,
        item_name: str,
        type_str: str,
        raw: Any,
    ) -> Optional[List[Tuple[str, float]]]:
        """
        解析 YAML 中的 display_args。

        - raw 为 None：视为未写有效列表，返回 None（与缺省键不同：此处为 YAML null）。
        - raw 为 []：返回空列表（显式不展示默认列，VARIABLE 表示不参与默认曲线）。
        - raw 为非空 list：解析为 (attr, ref)，ref 缺省为 DEFAULT_PLOT_SCALE_REF。
        """
        if raw is None:
            return None
        if not isinstance(raw, list):
            logger.warning("display_args 应为列表，已忽略: name=%s type=%s", item_name, type_str)
            return None
        if len(raw) == 0:
            return []

        specs: List[Tuple[str, float]] = []
        ptype = type_str.upper()
        for entry in raw:
            tok = str(entry).strip()
            m = _DISPLAY_ARG_TOKEN_RE.match(tok)
            if not m:
                logger.warning("display_args 项无法解析，已跳过: %s (name=%s)", tok, item_name)
                continue
            attr = m.group(1)
            ref_str = m.group(2)
            ref = float(ref_str) if ref_str else DEFAULT_PLOT_SCALE_REF
            if ref <= 0:
                logger.warning("display_args ref 须为正数，已改为默认 100: attr=%s name=%s", attr, item_name)
                ref = DEFAULT_PLOT_SCALE_REF
            if ptype == "VARIABLE" and attr != item_name:
                logger.warning(
                    "VARIABLE 的 display_args 属性名须与 name 一致，已跳过: %s != %s",
                    attr,
                    item_name,
                )
                continue
            specs.append((attr, ref))
        return specs

    # ------------------------------------------------------------------#
    # 拓扑排序
    # ------------------------------------------------------------------#
    def _topological_sort(self, items: List[ProgramItem]) -> List[ProgramItem]:
        """
        根据 inputs 依赖关系对 program items 做拓扑排序。

        - 旧语法项（inputs=None）无依赖，保持原序
        - 新语法项（inputs!=None）按依赖关系排序
        - 检测到环时，找环中 execute_first=True 的节点，切断其入边
        - 环中无 execute_first 则报错
        """
        from collections import deque

        if not items:
            return items

        all_names: Set[str] = {it.name for it in items}
        name_to_item: Dict[str, ProgramItem] = {it.name: it for it in items}

        # 构建依赖图: name -> set of names it depends on
        deps: Dict[str, Set[str]] = {}
        for it in items:
            if it.inputs is not None:
                dep_set: Set[str] = set()
                for source_expr in it.inputs.values():
                    source_node = source_expr.split(".")[0]
                    if source_node != it.name and source_node in all_names:
                        dep_set.add(source_node)
                deps[it.name] = dep_set
            else:
                deps[it.name] = set()

        # 反向图: name -> set of names that depend on it
        dependents: Dict[str, Set[str]] = {name: set() for name in all_names}
        for name, dep_set in deps.items():
            for dep in dep_set:
                dependents[dep].add(name)

        # Kahn's algorithm
        in_degree: Dict[str, int] = {name: len(deps[name]) for name in all_names}

        # 初始队列：按原始顺序加入 in_degree=0 的节点
        queue: deque = deque()
        for it in items:
            if in_degree[it.name] == 0:
                queue.append(it.name)

        sorted_names: List[str] = []

        while queue:
            name = queue.popleft()
            sorted_names.append(name)
            for dependent in dependents[name]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        # 检测环
        if len(sorted_names) < len(all_names):
            cycle_nodes = all_names - set(sorted_names)

            # 尝试用 execute_first 断环
            break_nodes = [n for n in cycle_nodes if name_to_item[n].execute_first]

            if not break_nodes:
                raise ValueError(
                    f"检测到依赖环，但环中无 execute_first=True 的节点。"
                    f"环中节点: {sorted(cycle_nodes)}。"
                    f"请在环中某个节点上设置 execute_first: true。"
                )

            # 断环：将 execute_first 节点的入度设为 0
            for bn in break_nodes:
                in_degree[bn] = 0
                queue.append(bn)

            while queue:
                name = queue.popleft()
                if name in sorted_names:
                    continue
                sorted_names.append(name)
                for dependent in dependents[name]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

            if len(sorted_names) < len(all_names):
                remaining = all_names - set(sorted_names)
                raise ValueError(
                    f"检测到依赖环，即使设置了 execute_first 仍无法解开。"
                    f"剩余节点: {sorted(remaining)}"
                )

        return [name_to_item[n] for n in sorted_names]

    # ------------------------------------------------------------------#
    # lag 需求分析
    # ------------------------------------------------------------------#
    def _analyze_lag_requirements(self, program_items: List[ProgramItem]) -> Dict[str, int]:
        """
        分析哪些变量/属性需要历史数据（被 [-N] 访问），并统计最大 lag。

        返回：
            { 变量或属性名: 需要支持的最大滞后步数 }
        例如：
            {"non_sense_1": 30, "pid1.mv": 10}
        """
        lag_requirements: Dict[str, int] = {}

        for item in program_items:
            expr = item.expression
            if not expr:
                continue

            try:
                # 使用 "exec" 模式解析，因为表达式可能是赋值语句（如 non_sense_3 = non_sense_1[-30]）
                tree = ast.parse(expr, mode="exec")
            except SyntaxError:
                # 表达式语法错误先忽略，后续可以在单独的校验阶段处理
                continue

            class LagVisitor(ast.NodeVisitor):
                def __init__(self) -> None:
                    self.local_requirements: Dict[str, int] = {}

                def visit_Subscript(self, node: ast.Subscript) -> None:
                    """
                    处理 v[-30] / pid1.mv[-10] 这种访问。

                    - node.value: 被下标访问的对象 (Name / Attribute)
                    - node.slice: 下标表达式（常量或一元负号表达式）
                    """
                    lag_steps = self._parse_lag_steps(node.slice)
                    if lag_steps <= 0:
                        self.generic_visit(node)
                        return

                    var_name = self._extract_var_name(node.value)
                    if not var_name:
                        self.generic_visit(node)
                        return

                    prev = self.local_requirements.get(var_name, 0)
                    if lag_steps > prev:
                        self.local_requirements[var_name] = lag_steps

                    self.generic_visit(node)

                @staticmethod
                def _parse_lag_steps(slice_node: ast.AST) -> int:
                    """从切片节点中解析出整数步数（例如 -30 -> 30）。"""
                    # 直接常量：[-30] 或 [30]
                    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, (int, float)):
                        return abs(int(slice_node.value))

                    # 一元运算：[-30]
                    if isinstance(slice_node, ast.UnaryOp) and isinstance(slice_node.operand, ast.Constant):
                        if isinstance(slice_node.operand.value, (int, float)):
                            return abs(int(slice_node.operand.value))

                    return 0

                @staticmethod
                def _extract_var_name(node: ast.AST) -> str:
                    """
                    提取被访问对象的“变量名”：
                    - Name -> "v1"
                    - Attribute 链（pid1.mv / ns1.pid1.mv） -> 拼成 dotted 字符串
                    其他情况返回空字符串。

                    支持任意深度的链式属性访问，沿 ``node.value`` 一直爬到 ``Name``。
                    """
                    parts: list[str] = []
                    while isinstance(node, ast.Attribute):
                        parts.insert(0, node.attr)
                        node = node.value
                    if isinstance(node, ast.Name):
                        parts.insert(0, node.id)
                        return ".".join(parts)
                    return ""

            visitor = LagVisitor()
            visitor.visit(tree)

            # 合并当前表达式的需求到全局
            for var_name, steps in visitor.local_requirements.items():
                prev = lag_requirements.get(var_name, 0)
                if steps > prev:
                    lag_requirements[var_name] = steps

        return lag_requirements


