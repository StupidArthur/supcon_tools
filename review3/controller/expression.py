"""
表达式节点（按周期执行）

支持 DSL 表达式的解析和执行：
- 四则混合运算、小括号
- 方法调用：instance.execute(...)
- 属性访问：instance.attribute
- 函数调用：abs(), sqrt() 等
- 历史数据访问：variable[-N] 或 instance.attribute[-N]
- 赋值表达式：variable = expression（用于 Variable 类型）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Callable, Optional

import ast

from components.utils.logger import get_logger
from .variable import VariableStore
from .instance import InstanceRegistry

logger = get_logger("expression")


class ExpressionError(Exception):
    """表达式执行相关错误。"""


@dataclass
class ExpressionConfig:
    """
    表达式节点配置。

    Attributes:
        name: 节点名称（变量名或实例名），如 "v1" 或 "pid1"。
        expression: 表达式字符串，例如：
                   - "pid1.execute(pv=tank1.level, sv=sin1.out)"
                   - "non_sense_3 = non_sense_1[-30] + 2 * non_sense_2"
    """

    name: str
    expression: str


class ExpressionEvaluator:
    """
    表达式求值器。

    支持：
    - 四则运算、括号
    - 方法调用（带关键字参数）
    - 属性访问
    - 函数调用
    - 历史数据访问（通过下标）
    - 赋值表达式
    
    性能优化：
    - 表达式预编译缓存，避免重复解析和编译
    """

    def __init__(
        self,
        vars_store: VariableStore,
        instances: Dict[str, Any],
    ) -> None:
        """
        初始化表达式求值器。

        Args:
            vars_store: 变量存储
            instances: 实例字典 {实例名: 实例对象}
        """
        self._vars = vars_store
        self._instances = instances
        # 实例级表达式编译缓存：表达式字符串 -> (编译后的字节码, 变量名集合)
        # 必须是实例级而不是类级，因为编译结果依赖 self._instances
        # （不同 evaluator 的 instances 字典可能不同）
        self._expr_cache: Dict[str, tuple[Any, set[str]]] = {}
        # 预构建实例代理字典（避免每次重新构建）
        self._instance_proxies: Dict[str, InstanceProxy] = {}
        for instance_name, instance in instances.items():
            self._instance_proxies[instance_name] = InstanceProxy(instance_name, instance, vars_store)

        # 预构建函数字典（避免每次调用 InstanceRegistry.list_functions）
        self._functions: Dict[str, Any] = {}
        for func_name in InstanceRegistry.list_functions():
            func = InstanceRegistry.get_function(func_name)
            if func:
                self._functions[func_name] = func

    def evaluate(self, expression: str) -> float:
        """
        执行表达式，返回数值结果（使用预编译缓存优化性能）。

        Args:
            expression: 表达式字符串

        Returns:
            计算结果（浮点数）
        """
        try:
            # 检查缓存
            if expression in self._expr_cache:
                compiled, variable_names = self._expr_cache[expression]
                # 构建执行环境（使用缓存的变量名集合）
                env = self._build_env_fast(variable_names)
                value = eval(compiled, {"__builtins__": {}}, env)
                return float(value)
            
            # 缓存未命中，进行完整解析和编译
            tree = ast.parse(expression, mode="eval")
            
            # 转换AST：将直接使用实例名的情况转换为 .out 属性访问
            tree = self._transform_instance_names(tree)
            
            # 验证 AST
            self._validate_ast(tree.body)
            
            # 提取所有变量名（不在 instances 中的名称）
            variable_names = self._extract_variable_names(tree.body)
            
            # 编译表达式
            compiled = compile(tree, filename="<expression>", mode="eval")
            
            # 缓存编译结果和变量名集合
            self._expr_cache[expression] = (compiled, variable_names)
            
            # 构建执行环境并执行
            env = self._build_env_fast(variable_names)
            value = eval(compiled, {"__builtins__": {}}, env)
            
            return float(value)
        except SyntaxError as exc:
            raise ExpressionError(f"表达式语法错误: {expression}, 错误: {exc}") from exc
        except NameError as exc:
            raise ExpressionError(f"表达式变量未定义: {expression}, 错误: {exc}") from exc
        except TypeError as exc:
            raise ExpressionError(f"表达式类型错误: {expression}, 错误: {exc}") from exc
        except ZeroDivisionError as exc:
            raise ExpressionError(f"表达式除零错误: {expression}, 错误: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ExpressionError(f"表达式执行失败: {expression}, 错误: {exc}") from exc
    
    def _build_env_fast(self, variable_names: set[str]) -> Dict[str, Any]:
        """
        快速构建执行环境（使用预构建的实例代理）。
        
        性能优化：
        - 缓存基础环境（实例代理、函数），只更新变量访问器
        - 使用 frozenset 作为缓存键
        
        Args:
            variable_names: 变量名集合
            
        Returns:
            环境字典
        """
        # 构建环境（不使用缓存，因为每次求值都需要最新的 VariableStore 引用）
        # 但是可以优化：预构建的实例代理和函数字典已经在 __init__ 中构建好了
        env: Dict[str, Any] = {}
        
        # 添加预构建的实例代理（这些代理持有 VariableStore 引用，可以重用）
        env.update(self._instance_proxies)
        
        # 添加无状态函数（使用预构建的函数字典）
        env.update(self._functions)
        
        # 添加变量访问器（支持历史数据访问）
        # 注意：只对不带`.`的变量名创建 VariableAccessor
        # 带`.`的位号名（如 ns1.sin1）应该被处理为实例代理，而不是 VariableAccessor
        # 同时，如果变量名是某个带`.`的位号名的前缀（如 ns1 是 ns1.sin1 的前缀），
        # 也应该被处理为实例代理，而不是 VariableAccessor
        
        # 性能优化：预先计算所有带`.`的变量名的前缀集合，避免 O(n*m) 的遍历
        dotted_var_prefixes: set[str] = set()
        for var_name in variable_names:
            if '.' in var_name:
                # 提取所有前缀（如 ns1.sin1.out -> ns1, ns1.sin1）
                parts = var_name.split('.')
                for i in range(1, len(parts)):
                    prefix = '.'.join(parts[:i])
                    dotted_var_prefixes.add(prefix)
        
        # 只对不带`.`且不是其他位号名前缀的变量名创建 VariableAccessor
        # 注意：如果变量名在 instances 中，应该使用 InstanceProxy（已经在 _instance_proxies 中预构建），而不是 VariableAccessor
        for var_name in variable_names:
            if '.' not in var_name:
                if var_name not in dotted_var_prefixes:
                    # 检查是否是 instances 中的实例名（如 v1 在 instances 中，应该使用 InstanceProxy）
                    if var_name in self._instances:
                        # 如果变量名在 instances 中，使用 InstanceProxy（已经在 _instance_proxies 中预构建，第150行已添加到 env）
                        # 这里不需要再次添加，因为已经在 env 中了
                        pass
                    else:
                        # 只有不带`.`且不是其他位号名前缀且不在 instances 中的才是真正的变量，创建 VariableAccessor
                        if var_name not in env:  # 避免覆盖已有的 InstanceProxy
                            env[var_name] = VariableAccessor(var_name, self._vars)
        
        # 对于属性访问中可能用到的实例名，如果不在 instances 中，创建一个代理
        # 允许从 VariableStore 中读取值（用于处理配置中不存在但 Redis 中有数据的场景）
        # 处理嵌套属性访问的情况（如 ns1.sin1.out 中的 ns1.sin1）
        for var_name in variable_names:
            if '.' in var_name:
                # 可能是完整的实例名（如 ns1.sin1），创建代理
                if var_name not in env and var_name not in self._instance_proxies:
                    # 检查是否是 instances 中的实例（可能是带命名空间的）
                    if var_name in self._instances:
                        # 如果完整的实例名在 instances 中，创建 InstanceProxy
                        env[var_name] = InstanceProxy(var_name, self._instances[var_name], self._vars)
                    else:
                        # 创建一个虚拟的实例代理，允许从 VariableStore 读取属性值
                        env[var_name] = MissingInstanceProxy(var_name, self._vars, self._instances)
                
                # 同时，为每一层创建代理（如 ns1.sin1.out 需要 ns1 和 ns1.sin1）
                parts = var_name.split('.')
                for i in range(1, len(parts)):
                    partial_name = '.'.join(parts[:i])
                    if partial_name not in env and partial_name not in self._instance_proxies:
                        # 检查是否是 instances 中的实例
                        if partial_name in self._instances:
                            env[partial_name] = InstanceProxy(partial_name, self._instances[partial_name], self._vars)
                        else:
                            env[partial_name] = MissingInstanceProxy(partial_name, self._vars, self._instances)
        
        return env

    def _transform_instance_names(self, tree: ast.AST) -> ast.AST:
        """
        转换AST：将直接使用实例名的情况转换为 .out 属性访问。
        
        例如：non_sense_1[-30] -> non_sense_1.out[-30]
              sqrt(non_sense_2) -> sqrt(non_sense_2.out)
        
        注意：只在以下情况下转换：
        - Name节点且名称在instances中
        - 且不是方法调用（如 instance.execute()）
        - 且不是属性访问（如 instance.attr）
        
        Args:
            tree: AST树
            
        Returns:
            转换后的AST树
        """
        class InstanceNameTransformer(ast.NodeTransformer):
            """
            AST 节点转换器：将直接使用实例名的情况转换为 .out 属性访问。
            
            转换规则：
            1. 如果遇到 Name 节点，且名称在 instances 中，且不是函数名，且不在属性访问中
               则转换为 Attribute 节点（instance_name.out）
            2. 如果遇到 Attribute 节点，标记 _in_attribute=True，避免重复转换
            3. 如果遇到 Call 节点（方法调用），不转换，但递归处理参数
            """
            def __init__(self, instances: Dict[str, Any]) -> None:
                self.instances = instances
                self._in_attribute = False  # 标记是否在属性访问中，避免重复转换
            
            def visit_Name(self, node: ast.Name) -> ast.AST:
                """
                处理 Name 节点（变量名或实例名）。
                
                转换逻辑：
                - 如果名称在 instances 中，且不是函数名，且不在属性访问中
                - 则转换为 instance_name.out 的 Attribute 节点
                """
                if node.id in self.instances and not self._in_attribute:
                    # 检查是否是函数名（函数名不需要转换）
                    func = InstanceRegistry.get_function(node.id)
                    if func is None:
                        # 转换为 instance_name.out
                        # 注意：需要设置 lineno 和 col_offset，否则 compile 会失败
                        new_name = ast.Name(id=node.id, ctx=ast.Load())
                        new_name.lineno = getattr(node, 'lineno', 1)
                        new_name.col_offset = getattr(node, 'col_offset', 0)
                        
                        new_attr = ast.Attribute(
                            value=new_name,
                            attr="out",
                            ctx=ast.Load()
                        )
                        new_attr.lineno = getattr(node, 'lineno', 1)
                        new_attr.col_offset = getattr(node, 'col_offset', 0)
                        return new_attr
                return node
            
            def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
                """
                处理 Attribute 节点（属性访问）。
                
                如果已经是属性访问（如 instance.attr），标记状态避免重复转换，
                然后递归处理子节点。
                """
                # 如果已经是属性访问，标记状态，然后递归处理
                # 如果 value 是 Name 且在 instances 中，说明已经是 instance.attr 的形式，不需要转换
                old_in_attribute = self._in_attribute
                self._in_attribute = True
                try:
                    # 递归处理子节点
                    self.generic_visit(node)
                    return node
                finally:
                    self._in_attribute = old_in_attribute
            
            def visit_Call(self, node: ast.Call) -> ast.AST:
                """
                处理 Call 节点（方法调用或函数调用）。
                
                方法调用（如 instance.execute()）不需要转换，
                但需要递归处理参数，因为参数中可能包含需要转换的实例名。
                """
                # 方法调用（如 instance.execute()）不需要转换
                # 但需要递归处理参数
                self.generic_visit(node)
                return node
        
        transformer = InstanceNameTransformer(self._instances)
        return transformer.visit(tree)
    
    def _extract_variable_names(self, node: ast.AST) -> set[str]:
        """
        提取表达式中的所有变量名（不在 instances 中的名称）。

        Args:
            node: AST 节点

        Returns:
            变量名集合（包含变量名和属性访问中的实例名，用于后续创建代理）
        """
        variable_names: set[str] = set()
        instance_names_in_attributes: set[str] = set()  # 属性访问中的实例名
        instances = self._instances

        class VariableNameVisitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self._in_attribute = False  # 标记是否在属性访问中
            
            def visit_Attribute(self, node: ast.Attribute) -> None:
                """
                访问属性节点时，标记在属性访问中，并递归访问 value。
                对于嵌套属性访问（如 ns1.sin1.out），需要提取完整的实例名（ns1.sin1）。
                """
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
                        # 无论是否在 instances 中，都添加到集合中（用于创建代理）
                        # 这样可以确保嵌套属性访问（如 ns1.sin1.out）能正确工作
                        func = InstanceRegistry.get_function(full_instance_name)
                        if func is None:
                            instance_names_in_attributes.add(full_instance_name)
                        
                        # 同时，为每一层也添加（如 ns1.sin1.out 需要 ns1）
                        for i in range(1, len(instance_name_parts)):
                            partial_name = ".".join(instance_name_parts[:i])
                            func_partial = InstanceRegistry.get_function(partial_name)
                            if func_partial is None:
                                instance_names_in_attributes.add(partial_name)
                
                # 递归访问 value
                self.visit(node.value)
                self._in_attribute = old_flag
            
            def visit_Name(self, node: ast.Name) -> None:
                if node.id not in instances:
                    # 检查是否是函数名
                    func = InstanceRegistry.get_function(node.id)
                    if func is None:
                        if self._in_attribute:
                            # 在属性访问中，且不在 instances 中，记录为可能的缺失实例
                            instance_names_in_attributes.add(node.id)
                        else:
                            # 不在属性访问中，且不是实例，且不是函数，则认为是变量
                            variable_names.add(node.id)

        visitor = VariableNameVisitor()
        visitor.visit(node)

        # 将属性访问中的实例名也添加到变量名集合中（用于创建缺失实例代理）
        variable_names.update(instance_names_in_attributes)

        return variable_names

    def _build_env(self, variable_names: set[str]) -> Dict[str, Any]:
        """
        构造表达式执行环境（兼容旧接口，内部调用_build_env_fast）。

        Args:
            variable_names: 变量名集合

        Returns:
            环境字典
        """
        return self._build_env_fast(variable_names)

    @staticmethod
    def _validate_ast(node: ast.AST) -> None:
        """
        验证 AST 节点是否允许。

        允许的节点类型：
        - Expression, BinOp, UnaryOp（运算）
        - Call（函数调用和方法调用，支持关键字参数）
        - Attribute（属性访问）
        - Subscript（历史数据访问）
        - Name, Constant, Num（名称、常量）
        - Assign（赋值表达式，用于 Variable 类型）
        """
        if isinstance(node, ast.Expression):
            ExpressionEvaluator._validate_ast(node.body)
        elif isinstance(node, ast.BinOp):
            ExpressionEvaluator._validate_ast(node.left)
            ExpressionEvaluator._validate_ast(node.right)
        elif isinstance(node, ast.UnaryOp):
            ExpressionEvaluator._validate_ast(node.operand)
        elif isinstance(node, ast.Call):
            # 允许函数调用和方法调用
            ExpressionEvaluator._validate_ast(node.func)
            for arg in node.args:
                ExpressionEvaluator._validate_ast(arg)
            # 允许关键字参数（用于方法调用）
            for keyword in node.keywords:
                ExpressionEvaluator._validate_ast(keyword.value)
        elif isinstance(node, ast.Attribute):
            # 允许属性访问
            ExpressionEvaluator._validate_ast(node.value)
        elif isinstance(node, ast.Subscript):
            # 允许历史数据访问
            ExpressionEvaluator._validate_ast(node.value)
            # slice 可能是 Index、Constant、UnaryOp 等
            if isinstance(node.slice, ast.Index):
                ExpressionEvaluator._validate_ast(node.slice.value)
            elif isinstance(node.slice, ast.Constant):
                pass  # 常量，允许
            elif isinstance(node.slice, ast.UnaryOp):
                ExpressionEvaluator._validate_ast(node.slice)
            else:
                ExpressionEvaluator._validate_ast(node.slice)
        elif isinstance(node, ast.Name):
            # 允许名称引用
            pass
        elif isinstance(node, ast.Constant):
            # 允许常量
            pass
        elif isinstance(node, ast.Assign):
            # 允许赋值表达式（用于 Variable 类型）
            for target in node.targets:
                ExpressionEvaluator._validate_ast(target)
            ExpressionEvaluator._validate_ast(node.value)
        else:
            raise ExpressionError(f"不允许的 AST 节点类型: {type(node).__name__}")


class InstanceProxy:
    """
    实例代理对象。

    用于在表达式中访问实例属性和调用方法。
    支持：
    - instance.attribute（当前值）
    - instance.attribute[-N]（历史值）
    - instance.execute(...)（方法调用）
    """

    def __init__(self, instance_name: str, instance: Any, vars_store: VariableStore) -> None:
        """
        初始化实例代理。

        Args:
            instance_name: 实例名称（如 "pid1"）
            instance: 实例对象
            vars_store: 变量存储
        """
        self._instance_name = instance_name
        self._instance = instance
        self._vars = vars_store

    def __getattr__(self, name: str) -> AttributeProxy:
        """
        获取属性代理。

        例如：pid1.mv -> AttributeProxy("pid1", "mv", ...)
        """
        return AttributeProxy(self._instance_name, name, self._instance, self._vars)

    def execute(self, **kwargs: Any) -> None:
        """
        调用实例的 execute 方法。

        例如：pid1.execute(pv=tank1.level, sv=sin1.out)
        """
        self._instance.execute(**kwargs)


class MissingInstanceProxy:
    """
    缺失实例代理对象。

    用于处理配置中不存在但 VariableStore 中有数据的实例。
    支持：
    - instance.attribute（从 VariableStore 读取当前值）
    - instance.attribute[-N]（从 VariableStore 读取历史值）
    - 嵌套属性访问（如 ns1.sin1.out）
    """

    def __init__(self, instance_name: str, vars_store: VariableStore, instances: Dict[str, Any] = None) -> None:
        """
        初始化缺失实例代理。

        Args:
            instance_name: 实例名称（如 "pid1" 或 "ns1.sin1"）
            vars_store: 变量存储
            instances: 所有实例字典（用于检查嵌套实例）
        """
        self._instance_name = instance_name
        self._vars = vars_store
        self._instances = instances or {}

    def __getattr__(self, name: str):
        """
        获取属性代理（从 VariableStore 读取值）。

        例如：pid1.mv -> AttributeProxy("pid1", "mv", None, ...)
              ns1.sin1 -> 如果 ns1.sin1 在 instances 中，返回 InstanceProxy；否则返回 AttributeProxy
        """
        # 检查是否是完整的实例名（如 ns1.sin1）
        full_name = f"{self._instance_name}.{name}"
        
        # 如果完整的实例名在 instances 中，返回 InstanceProxy
        # 这样可以支持嵌套属性访问（如 ns1.sin1.out）
        if full_name in self._instances:
            return InstanceProxy(full_name, self._instances[full_name], self._vars)
        
        # 否则，返回 AttributeProxy，从 VariableStore 读取值
        return AttributeProxy(self._instance_name, name, None, self._vars)


class AttributeProxy:
    """
    属性代理对象。

    支持：
    - 当前值访问：float(proxy) 或直接使用
    - 历史值访问：proxy[-N]
    """

    def __init__(
        self,
        instance_name: str,
        attr_name: str,
        instance: Any,
        vars_store: VariableStore,
    ) -> None:
        """
        初始化属性代理。

        Args:
            instance_name: 实例名称（如 "pid1"）
            attr_name: 属性名称（如 "mv"）
            instance: 实例对象
            vars_store: 变量存储
        """
        self._instance_name = instance_name
        self._attr_name = attr_name
        self._instance = instance
        self._vars = vars_store
        self._var_key = f"{instance_name}.{attr_name}"

    def __float__(self) -> float:
        """
        获取当前值（转换为浮点数）。

        优先从 VariableStore 获取（可能已更新），
        否则从实例属性获取。
        """
        # 优先从 VariableStore 获取
        value = self._vars.get(self._var_key)
        if value is not None:
            return float(value)
        # 否则从实例属性获取（如果实例存在）
        if self._instance is not None:
            return float(getattr(self._instance, self._attr_name, 0.0))
        # 如果实例不存在，返回默认值
        return 0.0
    
    def __int__(self) -> int:
        """转换为整数。"""
        return int(float(self))
    
    def __complex__(self) -> complex:
        """转换为复数。"""
        return complex(float(self))

    def __getitem__(self, lag_steps: int) -> float:
        """
        获取历史值。

        Args:
            lag_steps: 滞后步数（负数，如 -30 表示 30 步之前）

        Returns:
            历史值
        """
        # 转换为正数
        if lag_steps < 0:
            lag_steps = -lag_steps
        return float(self._vars.get_with_lag(self._var_key, lag_steps, 0.0))

    # 数值运算支持
    def __add__(self, other: Any) -> float:
        return float(self) + float(other)

    def __radd__(self, other: Any) -> float:
        return float(other) + float(self)

    def __mul__(self, other: Any) -> float:
        return float(self) * float(other)

    def __rmul__(self, other: Any) -> float:
        return float(other) * float(self)

    def __sub__(self, other: Any) -> float:
        return float(self) - float(other)

    def __rsub__(self, other: Any) -> float:
        return float(other) - float(self)

    def __truediv__(self, other: Any) -> float:
        return float(self) / float(other)

    def __rtruediv__(self, other: Any) -> float:
        return float(other) / float(self)
    
    def __lt__(self, other: Any) -> bool:
        return float(self) < float(other)
    
    def __le__(self, other: Any) -> bool:
        return float(self) <= float(other)
    
    def __gt__(self, other: Any) -> bool:
        return float(self) > float(other)
    
    def __ge__(self, other: Any) -> bool:
        return float(self) >= float(other)
    
    def __eq__(self, other: Any) -> bool:
        return float(self) == float(other)
    
    def __ne__(self, other: Any) -> bool:
        return float(self) != float(other)

    def __repr__(self) -> str:
        """字符串表示（用于调试）。"""
        return f"<AttributeProxy {self._var_key}={float(self)}>"


class VariableAccessor:
    """
    变量访问器。

    支持：
    - 当前值访问：float(accessor)
    - 历史值访问：accessor[-N]
    - 属性访问：accessor.attr（支持实例属性访问，如 pid_1.MV）
    """

    def __init__(self, var_name: str, vars_store: VariableStore) -> None:
        """
        初始化变量访问器。

        Args:
            var_name: 变量名称
            vars_store: 变量存储
        """
        self._var_name = var_name
        self._vars = vars_store

    def __float__(self) -> float:
        """获取当前值。"""
        return float(self._vars.get(self._var_name, 0.0))

    def __getitem__(self, lag_steps: int) -> float:
        """
        获取历史值。

        Args:
            lag_steps: 滞后步数（负数，如 -30 表示 30 步之前）
        """
        if lag_steps < 0:
            lag_steps = -lag_steps
        return float(self._vars.get_with_lag(self._var_name, lag_steps, 0.0))

    def __getattr__(self, name: str) -> Any:
        """
        属性访问：accessor.attr 形式（docstring 承诺）。

        委托给 AttributeProxy，让访问器支持
            float(accessor.attr)              # 当前值
            accessor.attr[-N]                 # 历史值
            accessor.attr + 1 / 1 + accessor.attr   # 算术
        """
        # 避免 deepcopy / pickle 等过程中的伪属性调用陷入递归
        if name.startswith("_"):
            raise AttributeError(name)
        return AttributeProxy(self._var_name, name, None, self._vars)
    

    # 数值运算支持
    def __add__(self, other: Any) -> float:
        return float(self) + float(other)

    def __radd__(self, other: Any) -> float:
        return float(other) + float(self)

    def __mul__(self, other: Any) -> float:
        return float(self) * float(other)

    def __rmul__(self, other: Any) -> float:
        return float(other) * float(self)

    def __sub__(self, other: Any) -> float:
        return float(self) - float(other)

    def __rsub__(self, other: Any) -> float:
        return float(other) - float(self)

    def __truediv__(self, other: Any) -> float:
        return float(self) / float(other)

    def __rtruediv__(self, other: Any) -> float:
        return float(other) / float(self)

    def __repr__(self) -> str:
        """字符串表示（用于调试）。"""
        return f"<VariableAccessor {self._var_name}={float(self)}>"


class ExpressionNode:
    """
    表达式节点（用于 Variable 类型）。

    每个周期执行一次表达式计算，结果写入 VariableStore。
    
    性能优化：
    - 表达式预编译缓存，避免重复解析
    """

    def __init__(
        self,
        config: ExpressionConfig,
        instances: Dict[str, Any],
        vars_store: VariableStore | None = None,
    ) -> None:
        """
        初始化表达式节点。

        Args:
            config: 表达式配置
            instances: 实例字典
            vars_store: 变量存储（用于预编译，可选）
        """
        self.config = config
        self._instances = instances
        
        # 预编译表达式（如果提供了vars_store）
        self._compiled_expr: Any | None = None
        self._expr_str: str | None = None
        self._variable_names: set[str] = set()
        self._evaluator: ExpressionEvaluator | None = None
        
        if vars_store is not None:
            self._precompile(vars_store)

    @property
    def name(self) -> str:
        """节点名称（输出变量名）。"""
        return self.config.name
    
    def _precompile(self, vars_store: VariableStore) -> None:
        """
        预编译表达式，提升执行性能。
        
        Args:
            vars_store: 变量存储
        """
        # 创建求值器
        self._evaluator = ExpressionEvaluator(vars_store, self._instances)
        
        # 检查是否是赋值表达式
        try:
            tree = ast.parse(self.config.expression, mode="exec")
            if isinstance(tree.body[0], ast.Assign):
                # 赋值表达式：提取右侧表达式
                if hasattr(ast, "unparse"):
                    self._expr_str = ast.unparse(tree.body[0].value)
                else:
                    parts = self.config.expression.split("=", 1)
                    self._expr_str = parts[1].strip() if len(parts) == 2 else self.config.expression
            else:
                self._expr_str = self.config.expression
        except SyntaxError:
            self._expr_str = self.config.expression
        
        # 预编译（触发缓存）
        if self._evaluator and self._expr_str:
            # 调用一次evaluate以触发缓存
            try:
                self._evaluator.evaluate(self._expr_str)
            except Exception as e:
                logger.debug("预编译失败: %s, 错误: %s", self._expr_str, e)

    def step(self, vars_store: VariableStore) -> float:
        """
        执行一个周期计算（使用预编译缓存优化性能）。

        支持赋值表达式：variable_name = expression
        如果表达式是赋值，则提取右侧表达式执行。

        Args:
            vars_store: 变量存储

        Returns:
            当前周期计算得到的值
        """
        # 如果已预编译，使用缓存的求值器
        if self._evaluator is not None and self._expr_str is not None:
            value = self._evaluator.evaluate(self._expr_str)
        else:
            # 未预编译，使用传统方式（兼容性）
            evaluator = ExpressionEvaluator(vars_store, self._instances)
            
            # 检查是否是赋值表达式
            try:
                tree = ast.parse(self.config.expression, mode="exec")
                if isinstance(tree.body[0], ast.Assign):
                    if hasattr(ast, "unparse"):
                        expr_str = ast.unparse(tree.body[0].value)
                    else:
                        parts = self.config.expression.split("=", 1)
                        expr_str = parts[1].strip() if len(parts) == 2 else self.config.expression
                    value = evaluator.evaluate(expr_str)
                else:
                    value = evaluator.evaluate(self.config.expression)
            except SyntaxError:
                try:
                    value = evaluator.evaluate(self.config.expression)
                except SyntaxError:
                    raise ExpressionError(f"表达式格式错误: {self.config.expression}")
        
        # 写入变量存储
        vars_store.set(self.name, value)
        
        return value


class AlgorithmNode:
    """
    算法节点（用于算法/模型类型）。

    每个周期调用实例的 execute 方法。
    
    性能优化：
    - 参数表达式预编译缓存，避免重复解析
    """

    def __init__(
        self,
        instance: Any,
        expression: str,
        stored_attributes: list[str],
        instance_name: str,
        instances: Dict[str, Any],
        vars_store: VariableStore | None = None,
    ) -> None:
        """
        初始化算法节点。

        Args:
            instance: 算法/模型实例
            expression: 表达式字符串（方法调用表达式）
            stored_attributes: 需要存储的属性列表
            instance_name: 实例名称
            instances: 所有实例字典（用于解析参数）
            vars_store: 变量存储（用于预编译，可选）
        """
        self._instance = instance
        self._expression = expression
        self._stored_attributes = stored_attributes
        self._instance_name = instance_name
        self._instances = instances
        
        # 解析表达式，提取方法调用的参数
        self._parsed_args = self._parse_expression(expression)
        
        # 预编译参数表达式（如果提供了vars_store）
        self._evaluator: ExpressionEvaluator | None = None
        
        if vars_store is not None:
            self._evaluator = ExpressionEvaluator(vars_store, instances)
            # 预编译所有参数表达式（触发缓存）
            for param_name, param_expr in self._parsed_args.items():
                try:
                    self._evaluator.evaluate(param_expr)
                except Exception:
                    # 如果预编译失败，运行时再处理
                    pass

    def _parse_expression(self, expression: str) -> Dict[str, str]:
        """
        解析表达式，提取方法调用的关键字参数。

        例如：pid1.execute(pv=tank1.level, sv=sin1.out)
        返回：{"pv": "tank1.level", "sv": "sin1.out"}

        解析逻辑：
        1. 使用 ast.parse 解析表达式为 AST
        2. 验证根节点是 Call 节点（方法调用）
        3. 遍历关键字参数，将参数值转换为字符串表达式
        4. 支持多种 AST 节点类型：Name、Attribute、Subscript、Constant 等

        Args:
            expression: 表达式字符串（必须是方法调用格式）

        Returns:
            参数字典 {参数名: 参数表达式字符串}

        Raises:
            ExpressionError: 如果表达式解析失败或不是方法调用
        """
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as e:
            raise ExpressionError(f"表达式解析失败: {expression}, 错误: {e}") from e

        if not isinstance(tree.body, ast.Call):
            raise ExpressionError(f"表达式必须是方法调用: {expression}")

        args: Dict[str, str] = {}
        for keyword in tree.body.keywords:
            # 将参数值转换为字符串（用于后续解析）
            if hasattr(ast, "unparse"):
                # Python 3.9+
                param_expr = ast.unparse(keyword.value)
            else:
                # 兼容旧版本：手动构建表达式字符串
                # 这里简化处理，对于简单情况可以工作
                # 对于复杂表达式，建议使用 Python 3.9+
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

    def step(self, vars_store: VariableStore) -> None:
        """
        执行一个周期（使用预编译缓存优化性能）。

        Args:
            vars_store: 变量存储
        """
        # 使用预编译的求值器或创建新的（惰性预编译，保存到 self 以复用）
        if self._evaluator is not None:
            evaluator = self._evaluator
        else:
            self._evaluator = ExpressionEvaluator(vars_store, self._instances)
            evaluator = self._evaluator
        
        resolved_args: Dict[str, float] = {}
        
        for param_name, param_expr in self._parsed_args.items():
            value = evaluator.evaluate(param_expr)
            resolved_args[param_name] = value

        # 调用 execute 方法
        self._instance.execute(**resolved_args)

        # 存储需要存储的属性
        for attr_name in self._stored_attributes:
            if hasattr(self._instance, attr_name):
                value = getattr(self._instance, attr_name)
                # 使用 instance_name.attribute_name 作为存储键
                vars_store.set(f"{self._instance_name}.{attr_name}", value)
