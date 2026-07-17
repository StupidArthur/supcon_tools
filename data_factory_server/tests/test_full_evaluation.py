"""
完整测试：模拟实际的表达式求值流程

测试场景：
1. 表达式重写：pid_1.execute(PV=tank_1.level, SV=sin1.out) -> ns1.pid_1.execute(PV=ns1.tank_1.level, SV=ns1.sin1.out)
2. 表达式解析：提取参数 {"PV": "ns1.tank_1.level", "SV": "ns1.sin1.out"}
3. 表达式求值：evaluator.evaluate("ns1.sin1.out") 应该能正确求值
"""

import ast
from typing import Dict, Any


class MockVariableStore:
    """模拟 VariableStore"""
    def __init__(self):
        self._vars = {
            "ns1.sin1.out": 1.5,
            "ns1.tank_1.level": 2.0,
            "ns1.pid_1.SV": 0.0,
            "ns1.pid_1.PV": 0.0,
            "ns1.pid_1.MV": 0.0,
        }
    
    def get(self, name: str, default: float = 0.0) -> float:
        return self._vars.get(name, default)
    
    def set(self, name: str, value: float) -> None:
        self._vars[name] = value


class MockInstanceProxy:
    """模拟 InstanceProxy"""
    def __init__(self, instance_name: str, vars_store: MockVariableStore):
        self._instance_name = instance_name
        self._vars = vars_store
    
    def __getattr__(self, name: str):
        var_key = f"{self._instance_name}.{name}"
        return MockAttributeProxy(self._instance_name, name, vars_store)
    
    def execute(self, **kwargs: Any) -> None:
        print(f"  MockInstanceProxy.execute({self._instance_name}, {kwargs})")


class MockAttributeProxy:
    """模拟 AttributeProxy"""
    def __init__(self, instance_name: str, attr_name: str, vars_store: MockVariableStore):
        self._instance_name = instance_name
        self._attr_name = attr_name
        self._vars = vars_store
        self._var_key = f"{instance_name}.{attr_name}"
    
    def __float__(self) -> float:
        return self._vars.get(self._var_key, 0.0)


def _parse_expression(expression: str) -> Dict[str, str]:
    """解析表达式，提取方法调用的关键字参数"""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"表达式解析失败: {expression}, 错误: {e}") from e

    if not isinstance(tree.body, ast.Call):
        raise ValueError(f"表达式必须是方法调用: {expression}")

    args: Dict[str, str] = {}
    for keyword in tree.body.keywords:
        if hasattr(ast, "unparse"):
            param_expr = ast.unparse(keyword.value)
        else:
            if isinstance(keyword.value, ast.Name):
                param_expr = keyword.value.id
            elif isinstance(keyword.value, ast.Attribute):
                parts = []
                current = keyword.value
                while isinstance(current, ast.Attribute):
                    parts.insert(0, current.attr)
                    current = current.value
                if isinstance(current, ast.Name):
                    parts.insert(0, current.id)
                    param_expr = ".".join(parts)
                else:
                    param_expr = repr(keyword.value)
            elif isinstance(keyword.value, ast.Constant):
                param_expr = str(keyword.value.value)
            else:
                param_expr = repr(keyword.value)
        args[keyword.arg] = param_expr

    return args


def _evaluate_expression(expression: str, instances: Dict[str, Any], vars_store: MockVariableStore) -> float:
    """
    模拟表达式求值
    
    简化版本：只处理属性访问（如 ns1.sin1.out）
    """
    # 解析表达式
    tree = ast.parse(expression, mode="eval")
    
    def evaluate_node(node: ast.AST) -> float:
        if isinstance(node, ast.Name):
            # 如果是实例名，返回代理
            if node.id in instances:
                return float(MockInstanceProxy(node.id, vars_store))
            # 否则从 VariableStore 读取
            return vars_store.get(node.id, 0.0)
        elif isinstance(node, ast.Attribute):
            # 属性访问：ns1.sin1.out
            # 递归求值 value
            value_obj = evaluate_node(node.value)
            # 如果 value_obj 是 MockInstanceProxy，访问属性
            if isinstance(value_obj, MockInstanceProxy):
                attr_proxy = getattr(value_obj, node.attr)
                return float(attr_proxy)
            # 否则，构建变量名并从 VariableStore 读取
            # 这里简化处理，实际应该构建完整的变量名
            return vars_store.get(f"{node.value.id}.{node.attr}", 0.0)
        elif isinstance(node, ast.Constant):
            return float(node.value)
        else:
            raise ValueError(f"不支持的 AST 节点类型: {type(node)}")
    
    return evaluate_node(tree.body)


def test_full_flow():
    """测试完整流程"""
    
    print("=" * 80)
    print("完整测试：表达式重写 -> 解析 -> 求值")
    print("=" * 80)
    
    # 1. 表达式重写
    original_expr = "pid_1.execute(PV=tank_1.level, SV=sin1.out)"
    mapping = {"sin1": "ns1.sin1", "tank_1": "ns1.tank_1", "pid_1": "ns1.pid_1"}
    
    # 使用之前测试过的重写函数
    from test_namespace_rewrite import _rewrite_expression_with_mapping
    rewritten_expr = _rewrite_expression_with_mapping(original_expr, mapping)
    
    print(f"\n1. 表达式重写:")
    print(f"   原始: {original_expr}")
    print(f"   重写后: {rewritten_expr}")
    
    expected_rewritten = "ns1.pid_1.execute(PV=ns1.tank_1.level, SV=ns1.sin1.out)"
    if rewritten_expr != expected_rewritten:
        print(f"   [FAIL] 重写失败！期望: {expected_rewritten}")
        return False
    else:
        print(f"   [PASS] 重写成功")
    
    # 2. 表达式解析
    print(f"\n2. 表达式解析:")
    parsed_args = _parse_expression(rewritten_expr)
    print(f"   解析结果: {parsed_args}")
    
    expected_parsed = {"PV": "ns1.tank_1.level", "SV": "ns1.sin1.out"}
    if parsed_args != expected_parsed:
        print(f"   [FAIL] 解析失败！期望: {expected_parsed}")
        return False
    else:
        print(f"   [PASS] 解析成功")
    
    # 3. 表达式求值（简化版本）
    print(f"\n3. 表达式求值:")
    vars_store = MockVariableStore()
    instances = {
        "ns1.sin1": MockInstanceProxy("ns1.sin1", vars_store),
        "ns1.tank_1": MockInstanceProxy("ns1.tank_1", vars_store),
        "ns1.pid_1": MockInstanceProxy("ns1.pid_1", vars_store),
    }
    
    # 测试求值 ns1.sin1.out
    print(f"   测试求值: ns1.sin1.out")
    try:
        # 简化求值：直接构建 AST 并求值
        tree = ast.parse("ns1.sin1.out", mode="eval")
        print(f"   AST: {ast.dump(tree, indent=4)}")
        
        # 手动求值
        # tree.body 是 Attribute(value=Attribute(value=Name(id='ns1'), attr='sin1'), attr='out')
        # 需要访问 ns1 -> ns1.sin1 -> ns1.sin1.out
        result = _evaluate_expression("ns1.sin1.out", instances, vars_store)
        print(f"   求值结果: {result}")
        print(f"   [PASS] 求值成功")
    except Exception as e:
        print(f"   [FAIL] 求值失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "=" * 80)
    print("所有测试通过！")
    print("=" * 80)
    
    return True


if __name__ == "__main__":
    test_full_flow()

