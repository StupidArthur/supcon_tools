"""
详细的性能分析脚本

分析各个步骤的耗时，找出性能瓶颈
"""

import sys
import time
import cProfile
import pstats
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 导入程序和函数（触发注册）
from components import programs  # noqa: F401
from components import functions  # noqa: F401

from controller.parser import DSLParser
from controller.engine import UnifiedEngine


def test_performance_detailed():
    """详细的性能分析"""
    
    print("=" * 80)
    print("详细的性能分析")
    print("=" * 80)
    
    # 解析配置文件
    config_path = project_root / "classical_config" / "test_bug.yaml"
    print(f"\n配置文件: {config_path}")
    
    parser = DSLParser()
    config = parser.parse_file(config_path)
    
    print(f"组态信息:")
    print(f"  - 程序实例数: {len([item for item in config.program if item.type.upper() != 'VARIABLE'])}")
    print(f"  - 变量数: {len([item for item in config.program if item.type.upper() == 'VARIABLE'])}")
    print()
    
    # 创建引擎
    print("创建引擎...")
    engine_start = time.time()
    engine = UnifiedEngine.from_program_config(config)
    engine_create_time = time.time() - engine_start
    print(f"引擎创建耗时: {engine_create_time:.4f} 秒")
    print()
    
    # 测试2000点
    cycles = 2000
    print(f"测试 {cycles} 个周期...")
    print("-" * 80)
    
    # 使用 cProfile 进行性能分析
    profiler = cProfile.Profile()
    profiler.enable()
    
    start_time = time.time()
    snapshots = engine.run_generator(cycles)
    end_time = time.time()
    
    profiler.disable()
    
    execution_time = end_time - start_time
    print(f"总执行时间: {execution_time:.4f} 秒")
    print(f"平均单周期耗时: {(execution_time / cycles) * 1000:.4f} 毫秒")
    print(f"吞吐量: {cycles / execution_time:.2f} 周期/秒")
    print()
    
    # 分析性能瓶颈
    print("性能分析（Top 20 最耗时的函数）:")
    print("-" * 80)
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumulative')
    stats.print_stats(20)
    
    print()
    print("=" * 80)
    print("测试完成！")
    print("=" * 80)


if __name__ == "__main__":
    test_performance_detailed()

