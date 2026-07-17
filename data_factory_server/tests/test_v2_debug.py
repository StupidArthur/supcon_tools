"""
调试 v2 永远是 0 的问题
"""

import ast
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from controller.parser import DSLParser
from controller.engine import UnifiedEngine
from controller.expression import ExpressionEvaluator
from controller.variable import VariableStore

# 导入程序和函数（触发注册）
from components import programs  # noqa: F401
from components import functions  # noqa: F401

def test_v2_debug():
    """调试 v2 永远是 0 的问题"""
    
    print("=" * 80)
    print("调试 v2 永远是 0 的问题")
    print("=" * 80)
    
    # 1. 解析配置文件
    config_path = project_root / "classical_config" / "test_bug.yaml"
    parser = DSLParser()
    config = parser.parse_file(config_path)
    
    # 2. 创建引擎
    engine = UnifiedEngine.from_program_config(config)
    
    # 3. 检查 v2 节点的表达式
    print(f"\n检查 v2 节点的表达式:")
    for node in engine._nodes:
        if hasattr(node, 'name') and node.name == 'v2':
            print(f"  v2 节点类型: {type(node).__name__}")
            print(f"  v2 表达式: {node.config.expression}")
            print(f"  v2 _expr_str: {getattr(node, '_expr_str', 'N/A')}")
            
            # 检查预编译的表达式
            if hasattr(node, '_evaluator') and node._evaluator:
                print(f"  v2 _evaluator 存在")
                # 手动测试表达式求值
                vars_store = engine.vars
                instances = engine._instances
                
                # 先执行一个周期，让 v1 有值
                engine._step_once()
                
                # 测试表达式求值
                expr_str = getattr(node, '_expr_str', node.config.expression)
                print(f"  测试表达式: {expr_str}")
                
                # 检查 AST 转换
                tree = ast.parse(expr_str, mode="eval")
                print(f"  原始 AST: {ast.dump(tree, indent=2)}")
                
                # 转换 AST
                transformed_tree = node._evaluator._transform_instance_names(tree)
                print(f"  转换后 AST: {ast.dump(transformed_tree, indent=2)}")
                
                # 提取变量名
                variable_names = node._evaluator._extract_variable_names(transformed_tree.body)
                print(f"  提取的变量名: {variable_names}")
                
                # 构建环境
                env = node._evaluator._build_env_fast(variable_names)
                print(f"  环境中的键: {sorted(env.keys())}")
                print(f"  env['v1'] 类型: {type(env.get('v1', 'N/A'))}")
                
                # 测试求值
                try:
                    compiled = compile(transformed_tree, filename="<expression>", mode="eval")
                    value = eval(compiled, {"__builtins__": {}}, env)
                    print(f"  求值结果: {value}")
                except Exception as e:
                    print(f"  求值失败: {e}")
                    import traceback
                    traceback.print_exc()
            break

if __name__ == "__main__":
    test_v2_debug()

