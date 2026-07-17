"""
组件元数据导出脚本

从 InstanceRegistry 导出所有算法/模型类型的 input_schema、stored_attributes、
default_params、param_descriptions 为 JSON，供可视化组态工具使用。

用法:
    python tools/export_metadata.py [--output config-tool/internal/config/components.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# 确保项目根目录在 sys.path 中
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def export_metadata() -> List[Dict[str, Any]]:
    """导出所有已注册组件的元数据。"""
    import components.programs  # noqa: F401  触发自动注册
    from controller.instance import InstanceRegistry

    result: List[Dict[str, Any]] = []

    for type_name in InstanceRegistry.list_algorithms():
        cls = InstanceRegistry.get_algorithm(type_name)
        if cls is None:
            continue
        result.append(_extract_meta(type_name, cls, "algorithm"))

    for type_name in InstanceRegistry.list_models():
        cls = InstanceRegistry.get_model(type_name)
        if cls is None:
            continue
        result.append(_extract_meta(type_name, cls, "model"))

    result.extend(_virtual_types())

    return result


def _extract_meta(type_name: str, cls: Any, category: str) -> Dict[str, Any]:
    """从类属性提取元数据。"""
    stored_attrs = getattr(cls, "stored_attributes", []) or []
    input_schema = getattr(cls, "input_schema", []) or []
    default_params = getattr(cls, "default_params", {}) or {}
    param_descs = getattr(cls, "param_descriptions", {}) or {}
    display_name = getattr(cls, "chinese_name", type_name)
    doc = getattr(cls, "doc", "")
    params_table = getattr(cls, "params_table", "")

    inputs = []
    for spec in input_schema:
        inputs.append({
            "name": spec.get("name", ""),
            "type": spec.get("type", "float"),
            "connectable": bool(spec.get("connectable", True)),
            "desc": spec.get("desc", ""),
        })

    outputs = []
    for attr in stored_attrs:
        outputs.append({
            "name": attr,
            "desc": param_descs.get(attr, attr),
        })

    params = []
    for pname, pdefault in default_params.items():
        params.append({
            "name": pname,
            "default": pdefault,
            "desc": param_descs.get(pname, pname),
        })

    return {
        "type": type_name,
        "category": category,
        "displayName": display_name,
        "inputs": inputs,
        "outputs": outputs,
        "params": params,
        "doc": doc,
        "paramsTable": params_table,
    }


def _virtual_types() -> List[Dict[str, Any]]:
    """Variable / Expression / Lag 三个虚拟类型的元数据。"""
    return [
        {
            "type": "Variable",
            "category": "variable",
            "displayName": "变量",
            "inputs": [],
            "outputs": [{"name": "out", "desc": "变量值"}],
            "params": [
                {"name": "value", "default": 0.0, "desc": "常量值"},
            ],
            "doc": "常量变量，持有固定值或由外部 OPC UA 写入。",
            "paramsTable": "",
        },
        {
            "type": "Expression",
            "category": "variable",
            "displayName": "表达式",
            "inputs": [],
            "outputs": [{"name": "out", "desc": "计算结果"}],
            "params": [
                {"name": "formula", "default": "0", "desc": "计算公式（可引用其他位号）"},
            ],
            "doc": "表达式变量，按公式计算结果。支持四则运算、函数调用、历史访问。",
            "paramsTable": "",
        },
        {
            "type": "Lag",
            "category": "variable",
            "displayName": "延迟",
            "inputs": [],
            "outputs": [{"name": "out", "desc": "延迟后的值"}],
            "params": [
                {"name": "source", "default": "", "desc": "被延迟的位号名"},
                {"name": "delay", "default": 1, "desc": "延迟步数"},
            ],
            "doc": "延迟变量，输出指定步数前的历史值。",
            "paramsTable": "",
        },
    ]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="导出组件元数据 JSON")
    parser.add_argument(
        "--output", "-o",
        default="config-tool/internal/config/components.json",
        help="输出文件路径",
    )
    args = parser.parse_args()

    metadata = export_metadata()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"导出 {len(metadata)} 个组件元数据到 {output_path}")
    for item in metadata:
        inputs_str = ", ".join(i["name"] for i in item["inputs"]) or "(无)"
        outputs_str = ", ".join(o["name"] for o in item["outputs"]) or "(无)"
        print(f"  {item['type']:20s} [{item['category']:10s}] "
              f"inputs=[{inputs_str}] outputs=[{outputs_str}]")


if __name__ == "__main__":
    main()
