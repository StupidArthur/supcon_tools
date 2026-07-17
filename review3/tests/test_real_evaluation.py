"""
真实场景测试：模拟实际的表达式求值流程

测试场景：
1. instances 中有 ns1.sin1, ns1.tank_1, ns1.pid_1
2. 表达式：ns1.sin1.out
3. 求值时，Python 会先访问 ns1，然后访问 .sin1，然后访问 .out
4. 需要确保 env 中有 ns1 和 ns1.sin1 的代理
"""

import ast
from typing import Dict, Any


class MockVariableStore:
    """模拟 VariableStore"""
    def __init__(self):
        self._vars = {
            "ns1.sin1.out": 1.5,
            "ns1.tank_1.level": 2.0,
        }
    
    def get(self, name: str, default: float = 0.0) -> float:
        return self._vars.get(name, default)


class MockInstanceProxy:
    """模拟 InstanceProxy"""
    def __init__(self, instance_name: str, vars_store: MockVariableStore):
        self._instance_name = instance_name
        self._vars = vars_store
    
    def __getattr__(self, name: str):
        var_key = f"{self._instance_name}.{name}"
        return MockAttributeProxy(self._instance_name, name, self._vars)
    
    def execute(self, **kwargs: Any) -> None:
        pass


class MockMissingInstanceProxy:
    """模拟 MissingInstanceProxy"""
    def __init__(self, instance_name: str, vars_store: MockVariableStore, instances: Dict[str, Any]):
        self._instance_name = instance_name
        self._vars = vars_store
        self._instances = instances
    
    def __getattr__(self, name: str):
        full_name = f"{self._instance_name}.{name}"
        if full_name in self._instances:
            return MockInstanceProxy(full_name, self._vars)
        return MockAttributeProxy(self._instance_name, name, self._vars)


class MockAttributeProxy:
    """模拟 AttributeProxy"""
    def __init__(self, instance_name: str, attr_name: str, vars_store: MockVariableStore):
        self._instance_name = instance_name
        self._attr_name = attr_name
        self._vars = vars_store
        self._var_key = f"{instance_name}.{attr_name}"
    
    def __float__(self) -> float:
        return self._vars.get(self._var_key, 0.0)


def _extract_variable_names(node: ast.AST, instances: Dict[str, Any]) -> set[str]:
    """提取表达式中的所有变量名"""
    variable_names: set[str] = set()
    instance_names_in_attributes: set[str] = set()
    
    class VariableNameVisitor(ast.NodeVisitor):
        def __init__(self):
            self._in_attribute = False
        
        def visit_Attribute(self, node: ast.Attribute) -> None:
            old_flag = self._in_attribute
            self._in_attribute = True
            
            # 构建完整的属性链，检查是否是实例名
            parts = []
            current = node
            while isinstance(current, ast.Attribute):
                parts.insert(0, current.attr)
                current = current.value
            
            # 如果最底层是 Name，构建完整的实例名
            if isinstance(current, ast.Name):
                instance_name_parts = [current.id] + parts[:-1]  # 排除最后一个属性（如 'out'）
                if instance_name_parts:
                    full_instance_name = ".".join(instance_name_parts)
                    func = None  # 简化：不检查函数名
                    if func is None:
                        instance_names_in_attributes.add(full_instance_name)
                    
                    # 同时，为每一层也添加（如 ns1.sin1.out 需要 ns1）
                    for i in range(1, len(instance_name_parts)):
                        partial_name = ".".join(instance_name_parts[:i])
                        instance_names_in_attributes.add(partial_name)
            
            self.visit(node.value)
            self._in_attribute = old_flag
        
        def visit_Name(self, node: ast.Name) -> None:
            if node.id not in instances:
                if self._in_attribute:
                    instance_names_in_attributes.add(node.id)
                else:
                    variable_names.add(node.id)
    
    visitor = VariableNameVisitor()
    visitor.visit(node)
    variable_names.update(instance_names_in_attributes)
    return variable_names


def _build_env_fast(variable_names: set[str], instances: Dict[str, Any], vars_store: MockVariableStore) -> Dict[str, Any]:
    """构建执行环境"""
    env: Dict[str, Any] = {}
    
    # 添加预构建的实例代理
    for instance_name, instance in instances.items():
        env[instance_name] = MockInstanceProxy(instance_name, vars_store)
    
    # 添加变量访问器（简化：跳过）
    
    # 处理嵌套属性访问
    for var_name in variable_names:
        if '.' in var_name:
            # 可能是完整的实例名（如 ns1.sin1），创建代理
            if var_name not in env:
                if var_name in instances:
                    env[var_name] = MockInstanceProxy(var_name, vars_store)
                else:
                    env[var_name] = MockMissingInstanceProxy(var_name, vars_store, instances)
            
            # 同时，为每一层创建代理（如 ns1.sin1.out 需要 ns1 和 ns1.sin1）
            parts = var_name.split('.')
            for i in range(1, len(parts)):
                partial_name = '.'.join(parts[:i])
                if partial_name not in env:
                    if partial_name in instances:
                        env[partial_name] = MockInstanceProxy(partial_name, vars_store)
                    else:
                        env[partial_name] = MockMissingInstanceProxy(partial_name, vars_store, instances)
    
    return env


def test_real_evaluation():
    """测试真实场景"""
    
    print("=" * 80)
    print("真实场景测试：表达式求值")
    print("=" * 80)
    
    # 模拟环境
    vars_store = MockVariableStore()
    instances = {
        "ns1.sin1": "mock_instance",
        "ns1.tank_1": "mock_instance",
        "ns1.pid_1": "mock_instance",
    }
    
    # 测试表达式
    expression = "ns1.sin1.out"
    print(f"\n测试表达式: {expression}")
    
    # 1. 解析 AST
    tree = ast.parse(expression, mode="eval")
    print(f"AST: {ast.dump(tree, indent=2)}")
    
    # 2. 提取变量名
    variable_names = _extract_variable_names(tree.body, instances)
    print(f"提取的变量名: {variable_names}")
    
    expected_vars = {"ns1.sin1", "ns1"}
    if variable_names != expected_vars:
        print(f"  [FAIL] 变量名提取失败！期望: {expected_vars}, 实际: {variable_names}")
        return False
    else:
        print(f"  [PASS] 变量名提取成功")
    
    # 3. 构建环境
    env = _build_env_fast(variable_names, instances, vars_store)
    print(f"环境中的键: {sorted(env.keys())}")
    
    expected_env_keys = {"ns1", "ns1.sin1", "ns1.tank_1", "ns1.pid_1"}
    if not all(key in env for key in expected_env_keys):
        print(f"  [FAIL] 环境构建失败！缺少键")
        return False
    else:
        print(f"  [PASS] 环境构建成功")
    
    # 4. 测试求值
    print(f"\n测试求值: {expression}")
    try:
        compiled = compile(tree, filename="<expression>", mode="eval")
        value = eval(compiled, {"__builtins__": {}}, env)
        print(f"求值结果: {value}")
        print(f"  [PASS] 求值成功")
    except Exception as e:
        print(f"  [FAIL] 求值失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "=" * 80)
    print("所有测试通过！")
    print("=" * 80)
    
    return True


if __name__ == "__main__":
    test_real_evaluation()

