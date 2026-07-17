"""
一次性导出执行器。

每次调用都会：
- 解析组态
- 创建临时引擎（GENERATOR）
- 执行指定步数
- 按模板导出为 CSV
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import tempfile

# 导入程序和函数（触发注册）
from components import programs  # noqa: F401
from components import functions  # noqa: F401

from controller.engine import UnifiedEngine
from controller.parser import DSLParser, ProgramConfig
from controller.clock import ClockMode
from components.utils.logger import get_logger, get_output_dir
from components.export_templates import ExportTemplate
from copy import deepcopy

logger = get_logger()

# 导出文件扩展名（与 export_format.file_format 对应）
EXPORT_EXT_BY_FORMAT = {"csv": ".csv", "xlsx": ".xlsx", "xls": ".xls"}


def _normalize_export_path(output_path: Path, file_format: str) -> Path:
    """若后缀与目标格式不一致则替换为正确扩展名。"""
    ext = EXPORT_EXT_BY_FORMAT.get((file_format or "csv").lower(), ".csv")
    if output_path.suffix.lower() != ext:
        return output_path.with_suffix(ext)
    return output_path


def _apply_namespace_to_config(config: ProgramConfig, namespace: str, parser: DSLParser) -> ProgramConfig:
    """
    为配置应用命名空间（与 ServiceManager._load_running_configs 相同的逻辑）。
    
    Args:
        config: 原始配置
        namespace: 命名空间
        parser: DSLParser 实例
    
    Returns:
        应用命名空间后的配置
    """
    if not namespace:
        return config
    
    # 第一步：收集所有实例名，构建完整的映射表
    all_instance_names = {item.name for item in config.program if item.type.upper() != "VARIABLE"}
    mapping: Dict[str, str] = {name: f"{namespace}.{name}" for name in all_instance_names}
    
    # 第二步：应用命名空间并合并 program items
    ns_items = []
    for item in config.program:
        ns_item = deepcopy(item)
        
        # 应用命名空间到 item 名称
        if item.name in mapping:
            ns_item.name = mapping[item.name]
        else:
            ns_item.name = f"{namespace}.{item.name}"
        
        # 重写表达式中的名称
        if ns_item.expression:
            ns_item.expression = _rewrite_expression_with_mapping(ns_item.expression, mapping)
        
        ns_items.append(ns_item)
    
    # 合并 lag_requirements（也需要应用命名空间）
    ns_lag_requirements = {}
    for var_name, max_lag_steps in config.lag_requirements.items():
        if '.' in var_name:
            parts = var_name.split('.', 1)
            instance_part = parts[0]
            attr_part = parts[1]
            if instance_part in mapping:
                namespaced_var_name = f"{mapping[instance_part]}.{attr_part}"
            else:
                namespaced_var_name = f"{namespace}.{var_name}"
        else:
            namespaced_var_name = f"{namespace}.{var_name}"
        ns_lag_requirements[namespaced_var_name] = max_lag_steps
    
    return ProgramConfig(
        clock=config.clock,
        program=ns_items,
        record_length=config.record_length,
        lag_requirements=ns_lag_requirements
    )


def _rewrite_expression_with_mapping(expression: str, mapping: Dict[str, str]) -> str:
    """
    使用 AST 将表达式中的名称按映射表替换（与 ServiceManager._rewrite_expression_with_mapping 相同的逻辑）。
    """
    import ast
    
    try:
        tree = ast.parse(expression, mode="exec")
    except SyntaxError:
        return expression

    class _Rewriter(ast.NodeTransformer):
        def __init__(self, mapping: Dict[str, str]) -> None:
            self.mapping = mapping

        def visit_Name(self, node: ast.Name) -> ast.AST:
            if node.id in self.mapping:
                return self._build_attr_chain(self.mapping[node.id], node)
            return node

        def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
            # 先递归访问子节点（处理嵌套属性访问）
            self.generic_visit(node)
            # 然后处理 instance.attr 的情况：如果 instance 在映射中，替换它
            if isinstance(node.value, ast.Name) and node.value.id in self.mapping:
                node.value = self._build_attr_chain(self.mapping[node.value.id], node.value)
            return node

        @staticmethod
        def _build_attr_chain(name: str, ref_node: ast.AST) -> ast.AST:
            """将 'ns.item' 转换为 Attribute 链，保持位置信息。"""
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

    try:
        rewriter = _Rewriter(mapping)
        new_tree = rewriter.visit(tree)
        ast.fix_missing_locations(new_tree)
        if hasattr(ast, "unparse"):
            return ast.unparse(new_tree)
        else:
            # Python < 3.9 没有 unparse，使用简单替换作为fallback
            result = expression
            for old_name, new_name in mapping.items():
                import re
                pattern = r'\b' + re.escape(old_name) + r'\b'
                result = re.sub(pattern, new_name, result)
            return result
    except Exception:
        return expression


def run_export(
    config_path: Optional[str] = None,
    dsl_content: Optional[str] = None,
    steps: int = 1000,
    template_name: str = "prediction",
    output_path: str | Path = None,
    cycle_time: Optional[float] = None,
    start_time: Optional[float] = None,
    time_format: Optional[str] = None,
    selected_variables: Optional[List[str]] = None,
    export_format: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    执行一次性导出。

    Args:
        config_path: 配置文件路径（当dsl_content为空时使用）
        dsl_content: DSL YAML 内容（字符串），优先使用
        steps: 总周期数
        template_name: 模板名称
        output_path: 输出文件路径，默认使用项目根目录的上一级目录下的 output 文件夹
        cycle_time: 执行周期（秒）
        start_time: 起始时间
        time_format: 时间格式
        selected_variables: 若提供则只导出这些列；None 表示按引擎 get_display_variables()（DSL display_args）筛选列
        export_format: 若提供则不再从 YAML 读导出格式；内含 header_rows、title_names、time_format、
            file_format（csv|xlsx|xls）、sheet_name（可选，Excel 默认「控制器」）

    Returns:
        { "output_path": str, "steps": int, "template": str, "file_format": str }
    """
    # 如果没有指定输出路径，使用默认输出目录
    if output_path is None:
        from datetime import datetime

        output_dir = get_output_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = ".csv"
        if export_format and export_format.get("file_format"):
            ext = EXPORT_EXT_BY_FORMAT.get(str(export_format["file_format"]).lower(), ".csv")
        output_path = Path(output_dir) / f"export_{timestamp}{ext}"
    else:
        output_path = Path(output_path)
        # 如果是相对路径，且不是绝对路径，则相对于默认输出目录
        if not output_path.is_absolute():
            output_path = Path(get_output_dir()) / output_path
    parser = DSLParser()
    
    # 优先使用dsl_content，否则使用config_path
    if dsl_content:
        # 将 DSL 内容写入临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(dsl_content)
            temp_path = f.name
        try:
            config: ProgramConfig = parser.parse_file(temp_path)
            # 如果配置文件在 running_config 目录下，从文件名提取命名空间并应用
            # 注意：这里无法直接判断，因为使用的是临时文件
            # 所以如果 dsl_content 中没有命名空间，则不应用命名空间
        finally:
            # 清理临时文件
            Path(temp_path).unlink(missing_ok=True)
    elif config_path:
        config_path_obj = Path(config_path)
        config: ProgramConfig = parser.parse_file(config_path)
        
        # 如果配置文件在 running_config 目录下，从文件名提取命名空间并应用
        # 检查路径中是否包含 running_config
        if "running_config" in str(config_path_obj):
            namespace = config_path_obj.stem  # 从文件名提取 namespace（去掉 .yaml 后缀）
            logger.info(f"检测到 running_config 目录下的配置文件，应用命名空间: {namespace}")
            # 应用命名空间到配置
            config = _apply_namespace_to_config(config, namespace, parser)
    else:
        raise ValueError("必须提供 config_path 或 dsl_content")
    
    # 如果提供了cycle_time等参数，修改时钟配置
    if cycle_time is not None:
        config.clock.cycle_time = cycle_time
    if start_time is not None:
        config.clock.start_time = start_time
    if time_format is not None:
        config.clock.time_format = time_format
    # 对于导出，我们希望每个周期都采样，所以设置 sample_interval = None（每个周期都采样）
    config.clock.sample_interval = None  # None 表示每个周期都采样
    config.clock.mode = ClockMode.GENERATOR
    
    engine = UnifiedEngine.from_program_config(config)
    snapshots = engine.run_generator(steps)
    export_columns = selected_variables
    if export_columns is None:
        export_columns = engine.get_display_variables()
        if snapshots:
            keys0 = set(snapshots[0].keys())
            export_columns = [k for k in export_columns if k in keys0]

    if export_format is None:
        output_path = _normalize_export_path(output_path, "csv")
        engine.export_to_csv(
            snapshots,
            template_name,
            output_path,
            selected_variables=export_columns,
        )
        return {
            "output_path": str(output_path),
            "steps": steps,
            "template": template_name,
            "file_format": "csv",
        }

    file_fmt = str(export_format.get("file_format", "csv")).lower()
    if file_fmt not in EXPORT_EXT_BY_FORMAT:
        raise ValueError(f"不支持的 file_format: {file_fmt}")
    output_path = _normalize_export_path(output_path, file_fmt)

    header_rows = int(export_format["header_rows"])
    title_names = str(export_format.get("title_names") or "")
    time_fmt_ef = str(export_format.get("time_format") or "%Y/%m/%d %H:%M:%S")
    sheet_name = export_format.get("sheet_name")
    if sheet_name is not None:
        sheet_name = str(sheet_name)

    inline_template = ExportTemplate(
        name="_inline_",
        header_rows=header_rows,
        title_names=title_names,
        time_format=time_fmt_ef,
        file_format=file_fmt,
        sheet_name=sheet_name if sheet_name else "控制器",
        uppercase_column_names=True,
    )

    engine.export_snapshots(
        snapshots,
        output_path,
        inline_template,
        file_format=file_fmt,
        sheet_name=inline_template.sheet_name,
        selected_variables=export_columns,
    )
    return {
        "output_path": str(output_path),
        "steps": steps,
        "template": template_name,
        "file_format": file_fmt,
    }

