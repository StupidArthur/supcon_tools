"""
测试 AlgorithmNode._parse_expression 是否能正确解析重写后的表达式

测试场景：
- 输入表达式：ns1.pid_1.execute(PV=ns1.tank_1.level, SV=ns1.sin1.out)
- 期望解析结果：{"PV": "ns1.tank_1.level", "SV": "ns1.sin1.out"}
"""

import ast
from typing import Dict


def _parse_expression(expression: str) -> Dict[str, str]:
    """
    解析表达式，提取方法调用的关键字参数。

    例如：pid1.execute(pv=tank1.level, sv=sin1.out)
    返回：{"pv": "tank1.level", "sv": "sin1.out"}
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"表达式解析失败: {expression}, 错误: {e}") from e

    if not isinstance(tree.body, ast.Call):
        raise ValueError(f"表达式必须是方法调用: {expression}")

    args: Dict[str, str] = {}
    for keyword in tree.body.keywords:
        # 将参数值转换为字符串（用于后续解析）
        if hasattr(ast, "unparse"):
            # Python 3.9+
            param_expr = ast.unparse(keyword.value)
        else:
            # 兼容旧版本：手动构建表达式字符串
            if isinstance(keyword.value, ast.Name):
                # 变量名：直接使用 id
                param_expr = keyword.value.id
            elif isinstance(keyword.value, ast.Attribute):
                # 属性访问：instance.attr 或 namespace.instance.attr
                # 递归构建属性链
                parts = []
                current = keyword.value
                while isinstance(current, ast.Attribute):
                    parts.insert(0, current.attr)
                    current = current.value
                if isinstance(current, ast.Name):
                    parts.insert(0, current.id)
                    param_expr = ".".join(parts)
                else:
                    # 复杂情况，使用 repr 作为后备
                    param_expr = repr(keyword.value)
            elif isinstance(keyword.value, ast.Subscript):
                # 历史数据访问：v1[-30] 或 tank1.level[-30] 或 ns1.sin1.out[-30]
                # 递归构建属性链
                value_node = keyword.value.value
                if isinstance(value_node, ast.Name):
                    base = value_node.id
                elif isinstance(value_node, ast.Attribute):
                    parts = []
                    current = value_node
                    while isinstance(current, ast.Attribute):
                        parts.insert(0, current.attr)
                        current = current.value
                    if isinstance(current, ast.Name):
                        parts.insert(0, current.id)
                        base = ".".join(parts)
                    else:
                        base = repr(value_node)
                else:
                    base = repr(value_node)
                
                # 处理 slice（支持负数索引，如 [-30]）
                if isinstance(keyword.value.slice, ast.UnaryOp) and isinstance(keyword.value.slice.op, ast.USub):
                    if isinstance(keyword.value.slice.operand, ast.Constant):
                        lag = keyword.value.slice.operand.value
                    else:
                        lag = "?"
                    param_expr = f"{base}[-{lag}]"
                else:
                    param_expr = f"{base}[{repr(keyword.value.slice)}]"
            elif isinstance(keyword.value, ast.Constant):
                # 常量：直接转换为字符串
                param_expr = str(keyword.value.value)
            else:
                # 复杂情况，使用 repr 作为后备
                param_expr = repr(keyword.value)
        args[keyword.arg] = param_expr

    return args


def test_parse():
    """测试表达式解析"""
    
    test_cases = [
        {
            "name": "重写后的表达式",
            "expression": "ns1.pid_1.execute(PV=ns1.tank_1.level, SV=ns1.sin1.out)",
            "expected": {"PV": "ns1.tank_1.level", "SV": "ns1.sin1.out"}
        },
        {
            "name": "原始表达式",
            "expression": "pid_1.execute(PV=tank_1.level, SV=sin1.out)",
            "expected": {"PV": "tank_1.level", "SV": "sin1.out"}
        },
        {
            "name": "嵌套属性访问",
            "expression": "ns1.sin1.out",
            "expected": None  # 不是方法调用，应该抛出异常
        }
    ]
    
    print("=" * 80)
    print("测试表达式解析功能")
    print("=" * 80)
    
    all_passed = True
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n测试 {i}: {test_case['name']}")
        print(f"  输入表达式: {test_case['expression']}")
        print(f"  期望结果: {test_case['expected']}")
        
        try:
            result = _parse_expression(test_case['expression'])
            print(f"  实际结果: {result}")
            
            if test_case['expected'] is None:
                print(f"  [FAIL] 应该抛出异常但没有")
                all_passed = False
            elif result == test_case['expected']:
                print(f"  [PASS] 通过")
            else:
                print(f"  [FAIL] 失败")
                all_passed = False
                
                # 显示 AST 结构以便调试
                print(f"\n  调试信息:")
                try:
                    tree = ast.parse(test_case['expression'], mode="eval")
                    print(f"  AST: {ast.dump(tree, indent=2)}")
                    print(f"  Keywords:")
                    for kw in tree.body.keywords:
                        print(f"    {kw.arg}: {ast.dump(kw.value, indent=4)}")
                except Exception as e:
                    print(f"  AST 解析错误: {e}")
        except Exception as e:
            if test_case['expected'] is None:
                print(f"  [PASS] 正确抛出异常: {e}")
            else:
                print(f"  [FAIL] 意外异常: {e}")
                import traceback
                traceback.print_exc()
                all_passed = False
    
    print("\n" + "=" * 80)
    if all_passed:
        print("所有测试通过！")
    else:
        print("部分测试失败！")
    print("=" * 80)
    
    return all_passed


if __name__ == "__main__":
    test_parse()

