"""
实时工程组态编译器

负责：
- 使用正式 DSL Parser 解析 YAML 获取顶层实例名
- 按副本数展开实例名称
- 全局唯一性校验
- 结构化冲突报告
- 编译合并：展开副本、重写引用、合并为单一 ProgramConfig YAML
"""

from __future__ import annotations

import copy
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .parser import DSLParser

MIN_REPLICAS = 1
MAX_REPLICAS = 100
MAX_EXPANDED_INSTANCES = 50_000


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    source_file: str
    replicas: int


@dataclass(frozen=True)
class InstanceOrigin:
    source_id: str
    source_file: str
    replica_index: int
    original_name: str


@dataclass(frozen=True)
class ExpandedInstance:
    name: str
    source_id: str
    source_file: str
    replica_index: int
    original_name: str


@dataclass(frozen=True)
class DuplicateInstance:
    name: str
    occurrences: tuple[InstanceOrigin, ...]


@dataclass
class ValidationResult:
    valid: bool
    instances: List[ExpandedInstance] = field(default_factory=list)
    duplicates: List[DuplicateInstance] = field(default_factory=list)


_parser = DSLParser()


def inspect_source(source: SourceSpec) -> List[str]:
    """
    使用正式 DSL Parser 解析 source.source_file，
    按 ProgramConfig 中的确定顺序返回顶层实例名。
    """
    config = _parser.parse_file(source.source_file)
    return [item.name for item in config.program]


def expand_instance_names(
    source: SourceSpec,
    original_names: List[str],
) -> List[ExpandedInstance]:
    """
    replica 0 保留原名；
    replica i（i >= 1）生成 name_{i}。
    """
    result: List[ExpandedInstance] = []
    for replica_index in range(source.replicas):
        for original_name in original_names:
            if replica_index == 0:
                name = original_name
            else:
                name = f"{original_name}_{replica_index}"
            result.append(ExpandedInstance(
                name=name,
                source_id=source.source_id,
                source_file=source.source_file,
                replica_index=replica_index,
                original_name=original_name,
            ))
    return result


def validate_sources(sources: List[SourceSpec]) -> ValidationResult:
    """
    解析全部来源、展开实例名称并执行全局唯一性检查。

    顺序保证：
    - sources 列表顺序（即 project.yaml 中 source 顺序）
    - replica_index 从 0 到 N-1
    - 原 DSL 中 parser 返回的程序项顺序
    """
    for source in sources:
        if source.replicas < MIN_REPLICAS or source.replicas > MAX_REPLICAS:
            raise ValueError(
                f"副本数必须在 {MIN_REPLICAS}~{MAX_REPLICAS} 之间，"
                f"source={source.source_id} replicas={source.replicas}"
            )

    all_instances: List[ExpandedInstance] = []
    for source in sources:
        original_names = inspect_source(source)
        expanded = expand_instance_names(source, original_names)
        all_instances.extend(expanded)

    if len(all_instances) > MAX_EXPANDED_INSTANCES:
        raise ValueError(
            f"展开后实例总数 {len(all_instances)} 超过上限 {MAX_EXPANDED_INSTANCES}"
        )

    seen: dict[str, List[InstanceOrigin]] = {}
    for inst in all_instances:
        origin = InstanceOrigin(
            source_id=inst.source_id,
            source_file=inst.source_file,
            replica_index=inst.replica_index,
            original_name=inst.original_name,
        )
        if inst.name not in seen:
            seen[inst.name] = []
        seen[inst.name].append(origin)

    duplicates: List[DuplicateInstance] = []
    for name, occurrences in seen.items():
        if len(occurrences) > 1:
            duplicates.append(DuplicateInstance(
                name=name,
                occurrences=tuple(occurrences),
            ))

    if duplicates:
        return ValidationResult(valid=False, instances=[], duplicates=duplicates)

    return ValidationResult(valid=True, instances=all_instances, duplicates=[])


def _build_rename_map(original_names: List[str], replica_index: int) -> Dict[str, str]:
    rename: Dict[str, str] = {}
    for name in original_names:
        if replica_index == 0:
            rename[name] = name
        else:
            rename[name] = f"{name}_{replica_index}"
    return rename


def _rewrite_reference(ref: str, rename: Dict[str, str]) -> str:
    """重写结构化引用 instance.attr 或 instance.attr[-N]，只替换实例段。"""
    import re
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)(.*)$", ref)
    if not m:
        return ref
    instance_part, rest = m.group(1), m.group(2)
    new_instance = rename.get(instance_part, instance_part)
    return new_instance + rest


_IDENT_RE = None
_REF_TOKEN_RE = None


class _InstanceRenamer:
    """AST 重写：只替换 ast.Name（实例引用），不动 Attribute.attr（属性名）。"""

    def __init__(self, rename: Dict[str, str]):
        self.rename = rename

    def visit_Name(self, node):
        if node.id in self.rename:
            node.id = self.rename[node.id]
        return node


def _rewrite_expression_tokens(expr: str, rename: Dict[str, str]) -> str:
    """
    回退重写：匹配 instance.attr 或裸 instance，只替换实例段，保留属性段。
    单 pass，避免 pid→pid_1 与 pid_1→pid_1_1 的次序串扰。
    """
    global _REF_TOKEN_RE
    if _REF_TOKEN_RE is None:
        import re
        _REF_TOKEN_RE = re.compile(
            r"\b([A-Za-z_][A-Za-z0-9_]*)(\.[A-Za-z_][A-Za-z0-9_]*)?\b"
        )

    def _repl(m):
        inst = m.group(1)
        attr = m.group(2) or ""
        return rename.get(inst, inst) + attr

    return _REF_TOKEN_RE.sub(_repl, expr)


def _rewrite_expression(expr: str, rename: Dict[str, str]) -> str:
    """
    基于 AST 重写表达式/公式中的实例引用。

    只替换 ast.Name 节点（实例引用），不替换 Attribute.attr（属性名）、
    字符串字面量或函数名。无法解析时回退到结构化 token 重写。
    """
    if not expr:
        return expr
    import ast

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return _rewrite_expression_tokens(expr, rename)

    renamer = _InstanceRenamer(rename)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            renamer.visit_Name(node)
    try:
        return ast.unparse(tree)
    except Exception:
        return _rewrite_expression_tokens(expr, rename)


def _replicate_program_item(
    item: Dict[str, Any],
    rename: Dict[str, str],
) -> Dict[str, Any]:
    new_item = copy.deepcopy(item)
    original_name = str(new_item["name"])
    new_item["name"] = rename.get(original_name, original_name)

    if new_item.get("inputs"):
        new_inputs = {}
        for port, ref in new_item["inputs"].items():
            new_inputs[port] = _rewrite_reference(str(ref), rename)
        new_item["inputs"] = new_inputs

    if new_item.get("expression"):
        new_item["expression"] = _rewrite_expression(str(new_item["expression"]), rename)

    if new_item.get("formula"):
        new_item["formula"] = _rewrite_expression(str(new_item["formula"]), rename)

    if new_item.get("source"):
        new_item["source"] = _rewrite_reference(str(new_item["source"]), rename)

    return new_item


def compile_project(sources: List[SourceSpec]) -> Dict[str, Any]:
    """
    编译实时工程：解析全部来源、展开副本、重写引用、合并为单一 DSL dict。

    复用 validate_sources 的展开和冲突检查规则。
    顺序保证与 validate_sources 一致。
    """
    validation = validate_sources(sources)
    if not validation.valid:
        dup_names = [d.name for d in validation.duplicates]
        raise ValueError(f"实例名称冲突，无法编译: {dup_names}")

    merged_program: List[Dict[str, Any]] = []
    clock_config: Dict[str, Any] | None = None

    for source in sources:
        path = Path(source.source_file)
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        if clock_config is None:
            clock_config = raw.get("clock", {})

        original_names = inspect_source(source)

        for replica_index in range(source.replicas):
            rename = _build_rename_map(original_names, replica_index)
            for item in raw.get("program", []) or []:
                merged_program.append(_replicate_program_item(item, rename))

    result: Dict[str, Any] = {}
    if clock_config:
        result["clock"] = clock_config
    else:
        result["clock"] = {"mode": "REALTIME", "cycle_time": 0.5}
    result["program"] = merged_program
    return result


def compile_project_to_file(sources: List[SourceSpec], output_path: str) -> str:
    merged = compile_project(sources)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        yaml.dump(merged, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return str(out)
