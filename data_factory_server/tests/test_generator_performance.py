"""
GENERATOR模式数据生成性能测试

测试不同规模下的数据生成性能，包括：
- 执行时间
- 吞吐量（周期/秒）
- 内存使用情况
"""

import sys
import time
import pathlib
from pathlib import Path

# 添加项目根目录到路径
project_root = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 导入程序和函数（触发注册）
from components import programs  # noqa: F401
from components import functions  # noqa: F401

from controller.parser import DSLParser
from controller.engine import UnifiedEngine


def test_performance(config_path: Path, cycle_counts: list[int]) -> None:
    """
    测试不同周期数下的性能
    
    Args:
        config_path: 配置文件路径
        cycle_counts: 要测试的周期数列表
    """
    print("=" * 80)
    print("GENERATOR模式数据生成性能测试")
    print("=" * 80)
    print(f"配置文件: {config_path}")
    print()
    
    # 解析配置文件
    parser = DSLParser()
    config = parser.parse_file(config_path)
    
    # 统计配置信息
    program_count = len([item for item in config.program if item.type.upper() != "VARIABLE"])
    variable_count = len([item for item in config.program if item.type.upper() == "VARIABLE"])
    total_items = len(config.program)
    
    print(f"组态信息:")
    print(f"  - 程序实例数: {program_count}")
    print(f"  - 变量数: {variable_count}")
    print(f"  - 总项数: {total_items}")
    print(f"  - 周期时间: {config.clock.cycle_time} 秒")
    print()
    
    # 创建引擎
    print("创建引擎...")
    engine_start = time.time()
    engine = UnifiedEngine.from_program_config(config)
    engine_create_time = time.time() - engine_start
    print(f"引擎创建耗时: {engine_create_time:.4f} 秒")
    print()
    
    # 测试不同规模
    results = []
    
    print("开始性能测试...")
    print("-" * 80)
    print(f"{'周期数':<12} {'执行时间(秒)':<15} {'吞吐量(周期/秒)':<20} {'单周期耗时(ms)':<15}")
    print("-" * 80)
    
    for cycles in cycle_counts:
        # 重新创建引擎（确保每次测试都是干净状态）
        engine = UnifiedEngine.from_program_config(config)
        
        # 执行测试
        start_time = time.time()
        snapshots = engine.run_generator(cycles)
        end_time = time.time()
        
        # 计算性能指标
        execution_time = end_time - start_time
        throughput = cycles / execution_time if execution_time > 0 else 0
        time_per_cycle = (execution_time / cycles) * 1000 if cycles > 0 else 0  # 毫秒
        
        results.append({
            'cycles': cycles,
            'execution_time': execution_time,
            'throughput': throughput,
            'time_per_cycle': time_per_cycle,
            'snapshot_count': len(snapshots)
        })
        
        print(f"{cycles:<12} {execution_time:<15.4f} {throughput:<20.2f} {time_per_cycle:<15.4f}")
    
    print("-" * 80)
    print()
    
    # 性能分析
    print("性能分析:")
    print("-" * 80)
    
    if len(results) > 1:
        # 计算平均吞吐量
        avg_throughput = sum(r['throughput'] for r in results) / len(results)
        print(f"平均吞吐量: {avg_throughput:.2f} 周期/秒")
        
        # 计算平均单周期耗时
        avg_time_per_cycle = sum(r['time_per_cycle'] for r in results) / len(results)
        print(f"平均单周期耗时: {avg_time_per_cycle:.4f} 毫秒")
        
        # 找出最快和最慢的
        fastest = max(results, key=lambda x: x['throughput'])
        slowest = min(results, key=lambda x: x['throughput'])
        print(f"最快吞吐量: {fastest['throughput']:.2f} 周期/秒 (周期数={fastest['cycles']})")
        print(f"最慢吞吐量: {slowest['throughput']:.2f} 周期/秒 (周期数={slowest['cycles']})")
    
    print()
    
    # 数据规模分析
    print("数据规模分析:")
    print("-" * 80)
    for r in results:
        # 估算数据大小（假设每个快照约1KB）
        estimated_size_mb = (r['snapshot_count'] * 1.0) / 1024
        print(f"周期数 {r['cycles']}: 生成 {r['snapshot_count']} 个快照, 估算大小约 {estimated_size_mb:.2f} MB")
    
    print()
    print("=" * 80)
    print("测试完成！")
    print("=" * 80)


def main():
    """主函数"""
    # 测试配置
    config_path = project_root / "classical_config" / "test_bug.yaml"
    
    # 测试不同规模的周期数
    # 从小到大，逐步增加
    # 可以通过环境变量 FAST_PERF_TEST 来跳过大规模测试
    import os
    fast_test = os.environ.get('FAST_PERF_TEST', '0') == '1'
    
    if fast_test:
        cycle_counts = [
            2000,       # 测试2000点（用户提到的规模）
        ]
    else:
        cycle_counts = [
            2000,       # 测试2000点（用户提到的规模）
            10000,      # 大规模
        ]
    
    # 如果配置文件不存在，使用默认配置
    if not config_path.exists():
        print(f"错误: 配置文件不存在: {config_path}")
        return
    
    test_performance(config_path, cycle_counts)


if __name__ == "__main__":
    main()

