"""
测试 test_bug.yaml 中 v2 永远是 0 的问题
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from controller.parser import DSLParser
from controller.engine import UnifiedEngine

# 导入程序和函数（触发注册）
from components import programs  # noqa: F401
from components import functions  # noqa: F401

def test_v2_bug():
    """测试 v2 永远是 0 的问题"""
    
    print("=" * 80)
    print("测试 test_bug.yaml 中 v2 永远是 0 的问题")
    print("=" * 80)
    
    # 1. 解析配置文件
    config_path = project_root / "classical_config" / "test_bug.yaml"
    print(f"\n1. 解析配置文件: {config_path}")
    
    parser = DSLParser()
    try:
        config = parser.parse_file(config_path)
        print(f"   [OK] 解析成功")
        print(f"   - 程序项数量: {len(config.program)}")
        for item in config.program:
            print(f"   - {item.name} ({item.type}): {item.expression}")
    except Exception as e:
        print(f"   [FAIL] 解析失败: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 2. 创建引擎
    print(f"\n2. 创建执行引擎")
    try:
        engine = UnifiedEngine.from_program_config(config)
        print(f"   [OK] 引擎创建成功")
        print(f"   - 节点数量: {len(engine._nodes)}")
        print(f"   - 实例数量: {len(engine._instances)}")
        print(f"   - 实例列表: {list(engine._instances.keys())}")
    except Exception as e:
        print(f"   [FAIL] 引擎创建失败: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 3. 执行几个周期
    print(f"\n3. 执行 10 个周期")
    try:
        snapshots = engine.run_generator(10)
        print(f"   [OK] 执行成功，生成了 {len(snapshots)} 个快照")
        
        # 检查 v1 和 v2 的值
        print(f"\n4. 检查 v1 和 v2 的值:")
        for i, snapshot in enumerate(snapshots[:10]):
            cycle_count = snapshot.get('cycle_count', i)
            v1_out = snapshot.get('v1.out', 'N/A')
            v2 = snapshot.get('v2', 'N/A')
            print(f"   Cycle {cycle_count}: v1.out={v1_out}, v2={v2}")
        
        # 检查 v2 是否都是 0
        v2_values = [s.get('v2', 0) for s in snapshots]
        if all(v == 0 for v in v2_values):
            print(f"\n   [BUG] v2 的所有值都是 0！")
        else:
            print(f"\n   [OK] v2 有非零值")
            
    except Exception as e:
        print(f"   [FAIL] 执行失败: {e}")
        import traceback
        traceback.print_exc()
        return

if __name__ == "__main__":
    test_v2_bug()

