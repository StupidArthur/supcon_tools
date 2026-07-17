"""
测试带多个点的位号名处理

问题场景：
- 表达式：ns1.pid_1.execute(PV=ns1.tank_1.level, SV=ns1.sin1.out)
- 当求值 ns1.sin1.out 时：
  1. Python 先访问 ns1
  2. 然后访问 ns1.sin1
  3. 然后访问 ns1.sin1.out
- 问题：如果 ns1.sin1 被设置为 VariableAccessor，那么访问 ns1.sin1.out 会失败
"""

import ast
from typing import Dict, Any, Set


def test_variable_name_extraction():
    """测试变量名提取"""
    
    print("=" * 80)
    print("测试变量名提取")
    print("=" * 80)
    
    # 测试表达式
    expression = "ns1.sin1.out"
    tree = ast.parse(expression, mode="eval")
    
    print(f"\n表达式: {expression}")
    print(f"AST: {ast.dump(tree, indent=2)}")
    
    # 模拟 _extract_variable_names 的逻辑
    variable_names: Set[str] = set()
    instance_names_in_attributes: Set[str] = set()
    instances = {}  # 空的，模拟不在 instances 中的情况
    
    class VariableNameVisitor(ast.NodeVisitor):
        def __init__(self):
            self._in_attribute = False
        
        def visit_Attribute(self, node: ast.Attribute) -> None:
            old_flag = self._in_attribute
            self._in_attribute = True
            
            # 构建完整的属性链
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
    visitor.visit(tree.body)
    variable_names.update(instance_names_in_attributes)
    
    print(f"\n提取的变量名: {variable_names}")
    
    expected = {"ns1", "ns1.sin1"}
    if variable_names == expected:
        print(f"  [PASS] 变量名提取正确")
    else:
        print(f"  [FAIL] 变量名提取错误！期望: {expected}, 实际: {variable_names}")
        return False
    
    return True


def test_env_building():
    """测试环境构建"""
    
    print("\n" + "=" * 80)
    print("测试环境构建")
    print("=" * 80)
    
    variable_names = {"ns1", "ns1.sin1"}
    instances = {
        "ns1.sin1": "mock_instance",  # 模拟实例存在
    }
    
    print(f"\n变量名: {variable_names}")
    print(f"实例: {list(instances.keys())}")
    
    # 模拟 _build_env_fast 的逻辑
    env: Dict[str, Any] = {}
    
    # 步骤1: 添加预构建的实例代理
    for instance_name, instance in instances.items():
        env[instance_name] = f"InstanceProxy({instance_name})"
    
    # 步骤2: 添加变量访问器（修复后：只对不带`.`的变量名创建 VariableAccessor）
    # 对于带`.`的位号名，不应该创建 VariableAccessor，应该创建实例代理
    for var_name in variable_names:
        if '.' not in var_name:
            # 只有不带`.`的才是真正的变量
            # 但是，如果这个变量名是带`.`的位号名的一部分（如 ns1.sin1.out 中的 ns1），
            # 那么它应该被处理为实例代理，而不是 VariableAccessor
            # 所以这里需要检查：如果 var_name 是某个带`.`的位号名的前缀，则跳过
            is_prefix = any(other_var.startswith(var_name + '.') for other_var in variable_names if '.' in other_var)
            if not is_prefix:
                env[var_name] = f"VariableAccessor({var_name})"
    
    # 步骤3: 处理带`.`的位号名，创建实例代理
    for var_name in variable_names:
        if '.' in var_name:
            if var_name not in env:
                if var_name in instances:
                    env[var_name] = f"InstanceProxy({var_name})"
                else:
                    env[var_name] = f"MissingInstanceProxy({var_name})"
            
            # 为每一层创建代理
            parts = var_name.split('.')
            for i in range(1, len(parts)):
                partial_name = '.'.join(parts[:i])
                if partial_name not in env:
                    if partial_name in instances:
                        env[partial_name] = f"InstanceProxy({partial_name})"
                    else:
                        env[partial_name] = f"MissingInstanceProxy({partial_name})"
    
    print(f"\n环境中的键: {sorted(env.keys())}")
    print(f"环境内容:")
    for key, value in sorted(env.items()):
        print(f"  {key}: {value}")
    
    # 检查：ns1 和 ns1.sin1 都应该是代理，而不是 VariableAccessor
    if "ns1" in env and "ns1.sin1" in env:
        if "VariableAccessor" not in env.get("ns1", "") and "VariableAccessor" not in env.get("ns1.sin1", ""):
            print(f"  [PASS] 环境构建正确")
            return True
        else:
            print(f"  [FAIL] 环境构建错误！ns1 或 ns1.sin1 被错误地设置为 VariableAccessor")
            return False
    else:
        print(f"  [FAIL] 环境构建错误！缺少 ns1 或 ns1.sin1")
        return False


if __name__ == "__main__":
    test1 = test_variable_name_extraction()
    test2 = test_env_building()
    
    print("\n" + "=" * 80)
    if test1 and test2:
        print("所有测试通过！")
    else:
        print("部分测试失败！")
    print("=" * 80)

