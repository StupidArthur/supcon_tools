"""
测试命名空间表达式重写功能

测试场景：
- 输入表达式：pid_1.execute(PV=tank_1.level, SV=sin1.out)
- 映射表：{"sin1": "ns1.sin1", "tank_1": "ns1.tank_1", "pid_1": "ns1.pid_1"}
- 期望输出：ns1.pid_1.execute(PV=ns1.tank_1.level, SV=ns1.sin1.out)
"""

import ast
from typing import Dict


def _rewrite_expression_with_mapping(expression: str, mapping: Dict[str, str]) -> str:
    """
    使用 AST 将表达式中的名称按映射表替换。
    """
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
            # 注意：generic_visit 会递归访问 node.value，但不会自动更新 node.value
            # 所以我们需要手动检查并更新
            self.generic_visit(node)
            # 然后处理 instance.attr 的情况：如果 instance 在映射中，替换它
            if isinstance(node.value, ast.Name) and node.value.id in self.mapping:
                # 替换 node.value 为命名空间后的属性链
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
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return expression


def test_rewrite():
    """测试表达式重写"""
    
    # 测试用例
    test_cases = [
        {
            "name": "PID execute with sin1.out",
            "expression": "pid_1.execute(PV=tank_1.level, SV=sin1.out)",
            "mapping": {"sin1": "ns1.sin1", "tank_1": "ns1.tank_1", "pid_1": "ns1.pid_1"},
            "expected": "ns1.pid_1.execute(PV=ns1.tank_1.level, SV=ns1.sin1.out)"
        },
        {
            "name": "Simple attribute access",
            "expression": "sin1.out",
            "mapping": {"sin1": "ns1.sin1"},
            "expected": "ns1.sin1.out"
        },
        {
            "name": "Nested attribute access",
            "expression": "tank_1.level",
            "mapping": {"tank_1": "ns1.tank_1"},
            "expected": "ns1.tank_1.level"
        },
        {
            "name": "Multiple attributes",
            "expression": "pid_1.execute(PV=tank_1.level, SV=sin1.out)",
            "mapping": {"sin1": "ns1.sin1", "tank_1": "ns1.tank_1", "pid_1": "ns1.pid_1"},
            "expected": "ns1.pid_1.execute(PV=ns1.tank_1.level, SV=ns1.sin1.out)"
        }
    ]
    
    print("=" * 80)
    print("测试命名空间表达式重写功能")
    print("=" * 80)
    
    all_passed = True
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n测试 {i}: {test_case['name']}")
        print(f"  输入表达式: {test_case['expression']}")
        print(f"  映射表: {test_case['mapping']}")
        print(f"  期望输出: {test_case['expected']}")
        
        result = _rewrite_expression_with_mapping(test_case['expression'], test_case['mapping'])
        print(f"  实际输出: {result}")
        
        if result == test_case['expected']:
            print(f"  [PASS] 通过")
        else:
            print(f"  [FAIL] 失败")
            all_passed = False
            
            # 显示 AST 结构以便调试
            print(f"\n  调试信息:")
            try:
                original_tree = ast.parse(test_case['expression'], mode="exec")
                result_tree = ast.parse(result, mode="exec")
                print(f"  原始 AST: {ast.dump(original_tree, indent=2)}")
                print(f"  结果 AST: {ast.dump(result_tree, indent=2)}")
            except Exception as e:
                print(f"  AST 解析错误: {e}")
    
    print("\n" + "=" * 80)
    if all_passed:
        print("所有测试通过！")
    else:
        print("部分测试失败！")
    print("=" * 80)
    
    return all_passed


if __name__ == "__main__":
    test_rewrite()

