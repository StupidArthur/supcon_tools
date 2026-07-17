"""
性能测试脚本

测试一个Engine能跑多少个namespace，以及各模块的性能情况。
使用"典型水箱液位控制"的组态作为标准。
"""

import sys
import time
import json
import psutil
import os
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 导入程序和函数（触发注册）
from components import programs  # noqa: F401
from components import functions  # noqa: F401

from controller.parser import DSLParser
from controller.engine import UnifiedEngine
from controller.realtime_publisher import RealtimeConfig
from services.service_manager import ServiceManager, ServiceManagerConfig
from components.utils.logger import get_logger

logger = get_logger()


def get_memory_usage() -> float:
    """获取当前进程的内存使用（MB）"""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024


def get_cpu_percent() -> float:
    """获取当前进程的CPU使用率（%）"""
    process = psutil.Process(os.getpid())
    return process.cpu_percent(interval=0.1)


def load_config_template() -> str:
    """加载典型水箱液位控制的配置模板"""
    config_path = project_root / "classical_config" / "典型水箱液位控制.yaml"
    with open(config_path, 'r', encoding='utf-8') as f:
        return f.read()


def create_namespace_config(namespace: str, template: str) -> str:
    """为指定namespace创建配置"""
    # 简单替换，实际应该使用更智能的方式
    # 这里假设配置文件中没有namespace冲突
    return template


def test_engine_performance(namespace_count: int, test_duration: float = 10.0) -> Dict[str, Any]:
    """
    测试指定数量namespace下的Engine性能
    
    Args:
        namespace_count: namespace数量
        test_duration: 测试持续时间（秒）
    
    Returns:
        性能指标字典
    """
    print(f"\n{'='*80}")
    print(f"测试 {namespace_count} 个 namespace")
    print(f"{'='*80}")
    
    # 加载配置模板
    template = load_config_template()
    parser = DSLParser()
    base_config = parser.parse(template)
    
    # 统计基础配置信息
    base_program_count = len([item for item in base_config.program if item.type.upper() != "VARIABLE"])
    base_variable_count = len([item for item in base_config.program if item.type.upper() == "VARIABLE"])
    
    print(f"基础配置信息 (单个namespace):")
    print(f"  - 程序实例数: {base_program_count}")
    print(f"  - 变量数: {base_variable_count}")
    print(f"  - 总项数: {len(base_config.program)}")
    print()
    
    # 记录初始内存
    initial_memory = get_memory_usage()
    
    # 创建引擎（先创建空引擎）
    print("创建引擎...")
    engine_start = time.time()
    
    # 创建空配置的引擎
    from controller.engine import EngineConfig
    from controller.clock import ClockConfig, ClockMode
    from controller.parser import ProgramConfig
    
    # 创建空配置
    empty_program_config = ProgramConfig(
        clock=base_config.clock,
        program=[],
        record_length=0,
        lag_requirements={},
    )
    
    engine = UnifiedEngine.from_program_config(empty_program_config)
    engine_create_time = time.time() - engine_start
    
    # 逐个加载namespace配置
    print(f"加载 {namespace_count} 个 namespace 配置...")
    load_start = time.time()
    
    for i in range(namespace_count):
        namespace = f"ns{i+1}" if i > 0 else ""
        try:
            engine.load_config(base_config, namespace=namespace)
            if i < 5 or i == namespace_count - 1:  # 只显示前5个和最后一个
                print(f"  - 已加载 namespace: {namespace or '(default)'}")
        except Exception as e:
            print(f"  - 加载 namespace {namespace} 失败: {e}")
            logger.error(f"加载namespace失败: {e}", exc_info=True)
            break
    
    load_time = time.time() - load_start
    engine_memory = get_memory_usage()
    
    # 统计实际加载的配置
    total_program_count = len([item for item in engine._program_items if item.type.upper() != "VARIABLE"])
    total_variable_count = len([item for item in engine._program_items if item.type.upper() == "VARIABLE"])
    
    print(f"\n合并后配置信息:")
    print(f"  - 总程序实例数: {total_program_count}")
    print(f"  - 总变量数: {total_variable_count}")
    print(f"  - 总项数: {len(engine._program_items)}")
    print(f"  - 引擎创建耗时: {engine_create_time:.4f} 秒")
    print(f"  - 配置加载耗时: {load_time:.4f} 秒")
    print(f"  - 引擎内存占用: {engine_memory - initial_memory:.2f} MB")
    print()
    
    # 启用实时数据发布（模拟实际运行环境）
    try:
        realtime_config = RealtimeConfig(
            redis_host=os.getenv("REDIS_HOST", "localhost"),
            redis_port=int(os.getenv("REDIS_PORT", "6379")),
            redis_db=int(os.getenv("REDIS_DB", "0")),
            redis_password=os.getenv("REDIS_PASSWORD"),
        )
        engine.enable_realtime_data(realtime_config, enable_message_bus=False)
        print("实时数据发布已启用")
    except Exception as e:
        print(f"警告: 无法启用实时数据发布: {e}")
    
    # 切换到GENERATOR模式（快速运行，不sleep）
    from controller.clock import ClockMode
    engine.clock.config.mode = ClockMode.GENERATOR
    
    # 运行测试（使用GENERATOR模式快速运行）
    print(f"运行测试 {test_duration} 秒 (GENERATOR模式)...")
    
    execution_times = []
    cycle_counts = []
    start_time = time.time()
    last_check_time = start_time
    
    # 计算需要运行的周期数（基于cycle_time和test_duration）
    # 但GENERATOR模式下会快速运行，所以我们需要基于实际时间来控制
    target_cycles = int(test_duration / engine.clock.config.cycle_time) if engine.clock.config.cycle_time > 0 else 10000
    
    try:
        cycle_count = 0
        # 使用run_generator方法，但需要手动控制时间
        # 或者使用run_realtime但设置环境变量
        os.environ['FAST_TEST'] = '1'  # 让run_realtime使用GENERATOR模式
        
        for snapshot in engine.run_realtime():
            cycle_count += 1
            
            # 记录执行时间
            current_time = time.time()
            if cycle_count % 100 == 0:  # 每100个周期记录一次
                execution_times.append(current_time - last_check_time)
                cycle_counts.append(cycle_count)
                last_check_time = current_time
            
            # 检查是否达到测试时长
            if current_time - start_time >= test_duration:
                break
                
            # 安全限制：如果周期数过多，也停止（防止无限循环）
            if cycle_count >= target_cycles * 10:  # 允许10倍余量
                break
    except KeyboardInterrupt:
        print("\n测试被用户中断")
    except Exception as e:
        print(f"\n测试过程中出错: {e}")
        logger.error(f"测试出错: {e}", exc_info=True)
    finally:
        # 清理环境变量
        if 'FAST_TEST' in os.environ:
            del os.environ['FAST_TEST']
    
    end_time = time.time()
    total_time = end_time - start_time
    
    # 计算性能指标
    if execution_times:
        avg_execution_time = sum(execution_times) / len(execution_times)
        avg_cycles_per_second = 100 / avg_execution_time if avg_execution_time > 0 else 0
    else:
        avg_execution_time = 0
        avg_cycles_per_second = 0
    
    final_memory = get_memory_usage()
    cpu_usage = get_cpu_percent()
    
    # 获取诊断信息（如果有）
    diagnostic_info = {}
    if hasattr(engine, '_diagnostic_provider') and engine._diagnostic_provider:
        try:
            diagnostics = engine._diagnostic_provider.collect_diagnostics()
            for item in diagnostics:
                diagnostic_info[item.name] = item.value
        except Exception as e:
            logger.debug(f"无法获取诊断信息: {e}")
    
    result = {
        'namespace_count': namespace_count,
        'total_program_count': total_program_count,
        'total_variable_count': total_variable_count,
        'total_items': len(engine._program_items),
        'engine_create_time': engine_create_time,
        'load_time': load_time,
        'test_duration': total_time,
        'total_cycles': cycle_count,
        'avg_execution_time': avg_execution_time,
        'avg_cycles_per_second': avg_cycles_per_second,
        'throughput': cycle_count / total_time if total_time > 0 else 0,
        'initial_memory_mb': initial_memory,
        'engine_memory_mb': engine_memory,
        'final_memory_mb': final_memory,
        'memory_increase_mb': final_memory - initial_memory,
        'cpu_percent': cpu_usage,
        'diagnostic_info': diagnostic_info,
    }
    
    print(f"\n性能指标:")
    print(f"  - 总周期数: {cycle_count}")
    print(f"  - 测试时长: {total_time:.2f} 秒")
    print(f"  - 吞吐量: {result['throughput']:.2f} 周期/秒")
    print(f"  - 平均执行时间: {avg_execution_time*1000:.4f} 毫秒/100周期")
    print(f"  - 内存占用: {final_memory - initial_memory:.2f} MB")
    print(f"  - CPU使用率: {cpu_usage:.1f}%")
    
    return result


def test_service_manager_performance(namespace_count: int, test_duration: float = 10.0) -> Dict[str, Any]:
    """
    测试ServiceManager（包含所有服务）的性能
    
    Args:
        namespace_count: namespace数量
        test_duration: 测试持续时间（秒）
    
    Returns:
        性能指标字典
    """
    print(f"\n{'='*80}")
    print(f"测试 ServiceManager ({namespace_count} 个 namespace)")
    print(f"{'='*80}")
    
    # 创建ServiceManager配置
    config = ServiceManagerConfig(
        redis_host=os.getenv("REDIS_HOST", "localhost"),
        redis_port=int(os.getenv("REDIS_PORT", "6379")),
        redis_db=int(os.getenv("REDIS_DB", "0")),
        redis_password=os.getenv("REDIS_PASSWORD"),
        enable_engine=True,
        enable_storage=True,
        enable_opcua=True,
    )
    
    service_manager = ServiceManager(config)
    
    # 记录初始资源
    initial_memory = get_memory_usage()
    process = psutil.Process(os.getpid())
    
    # 启动所有服务
    print("启动所有服务...")
    start_time = time.time()
    start_results = service_manager.start_all()
    startup_time = time.time() - start_time
    
    print(f"服务启动耗时: {startup_time:.4f} 秒")
    print(f"  - Engine: {'OK' if start_results.get('engine') else 'FAIL'}")
    print(f"  - StorageService: {'OK' if start_results.get('storage') else 'FAIL'}")
    print(f"  - OPCUA Server: {'OK' if start_results.get('opcua') else 'FAIL'}")
    print()
    
    # 加载多个namespace的配置
    template = load_config_template()
    parser = DSLParser()
    base_config = parser.parse(template)
    
    print(f"加载 {namespace_count} 个 namespace 配置...")
    load_start = time.time()
    for i in range(namespace_count):
        namespace = f"ns{i+1}" if i > 0 else ""
        try:
            service_manager.engine_runner.load_config(base_config, namespace=namespace)
            print(f"  - 已加载 namespace: {namespace or '(default)'}")
        except Exception as e:
            print(f"  - 加载 namespace {namespace} 失败: {e}")
            logger.error(f"加载namespace失败: {e}", exc_info=True)
    
    load_time = time.time() - load_start
    print(f"配置加载耗时: {load_time:.4f} 秒")
    print()
    
    # 等待服务稳定运行
    print("等待服务稳定运行...")
    time.sleep(2.0)
    
    # 监控运行状态
    print(f"监控运行状态 {test_duration} 秒...")
    monitor_start = time.time()
    
    metrics = {
        'engine_cycles': [],
        'storage_writes': [],
        'memory_usage': [],
        'cpu_usage': [],
    }
    
    try:
        while time.time() - monitor_start < test_duration:
            # 获取服务状态
            status = service_manager.get_services_status()
            
            # 获取诊断信息
            try:
                diagnostic_info = service_manager.get_diagnostic_info()
                
                # Engine诊断
                if 'engine' in diagnostic_info:
                    engine_diag = diagnostic_info['engine']
                    if 'cycle_count' in engine_diag:
                        metrics['engine_cycles'].append(engine_diag['cycle_count'])
            except Exception as e:
                logger.debug(f"获取诊断信息失败: {e}")
            
            # 记录资源使用
            metrics['memory_usage'].append(get_memory_usage())
            metrics['cpu_usage'].append(get_cpu_percent())
            
            time.sleep(1.0)  # 每秒采样一次
            
    except KeyboardInterrupt:
        print("\n监控被用户中断")
    
    monitor_time = time.time() - monitor_start
    
    # 计算统计信息
    final_memory = get_memory_usage()
    avg_cpu = sum(metrics['cpu_usage']) / len(metrics['cpu_usage']) if metrics['cpu_usage'] else 0
    max_memory = max(metrics['memory_usage']) if metrics['memory_usage'] else final_memory
    
    # 获取最终诊断信息
    final_diagnostics = {}
    try:
        diagnostic_info = service_manager.get_diagnostic_info()
        final_diagnostics = diagnostic_info
    except Exception as e:
        logger.debug(f"获取最终诊断信息失败: {e}")
    
    result = {
        'namespace_count': namespace_count,
        'startup_time': startup_time,
        'load_time': load_time,
        'monitor_time': monitor_time,
        'initial_memory_mb': initial_memory,
        'final_memory_mb': final_memory,
        'max_memory_mb': max_memory,
        'memory_increase_mb': final_memory - initial_memory,
        'avg_cpu_percent': avg_cpu,
        'final_diagnostics': final_diagnostics,
    }
    
    print(f"\n性能指标:")
    print(f"  - 启动耗时: {startup_time:.4f} 秒")
    print(f"  - 配置加载耗时: {load_time:.4f} 秒")
    print(f"  - 监控时长: {monitor_time:.2f} 秒")
    print(f"  - 内存占用: {final_memory - initial_memory:.2f} MB")
    print(f"  - 最大内存: {max_memory - initial_memory:.2f} MB")
    print(f"  - 平均CPU使用率: {avg_cpu:.1f}%")
    
    # 关闭服务
    print("\n关闭服务...")
    try:
        service_manager.close()
    except Exception as e:
        logger.error(f"关闭服务失败: {e}", exc_info=True)
    
    return result


def main():
    """主函数"""
    print("="*80)
    print("性能测试 - Engine Namespace容量测试")
    print("="*80)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 测试参数
    namespace_counts = [1, 5, 10, 20, 50, 100]  # 测试不同数量的namespace
    test_duration = 10.0  # 每个测试运行10秒
    
    # 存储所有测试结果
    engine_results = []
    service_results = []
    
    print("="*80)
    print("阶段1: Engine单独性能测试")
    print("="*80)
    
    # 测试Engine单独性能
    for ns_count in namespace_counts:
        try:
            result = test_engine_performance(ns_count, test_duration)
            engine_results.append(result)
            
            # 如果性能下降明显，提前停止（GENERATOR模式下应该能达到很高的吞吐量）
            if result['throughput'] < 100:  # GENERATOR模式下，吞吐量应该远高于100周期/秒
                print(f"\n警告: 吞吐量过低 ({result['throughput']:.2f} 周期/秒)，可能存在问题")
                # 不停止，继续测试下一个
        except Exception as e:
            print(f"\n错误: 测试 {ns_count} 个namespace时失败: {e}")
            logger.error(f"测试失败: {e}", exc_info=True)
            break
    
    print("\n" + "="*80)
    print("阶段2: ServiceManager完整性能测试")
    print("="*80)
    print("注意: ServiceManager测试会启动所有服务（Engine、StorageService、OPCUA Server）")
    print("      测试时间可能较长，请耐心等待...")
    print()
    
    # 测试ServiceManager完整性能（选择几个关键点）
    test_namespace_counts = [1, 10, 20]  # 减少测试点，因为完整测试较慢
    for ns_count in test_namespace_counts:
        try:
            result = test_service_manager_performance(ns_count, test_duration)
            service_results.append(result)
        except Exception as e:
            print(f"\n错误: ServiceManager测试 {ns_count} 个namespace时失败: {e}")
            logger.error(f"ServiceManager测试失败: {e}", exc_info=True)
            break
    
    # 输出汇总报告
    print("\n" + "="*80)
    print("测试汇总报告")
    print("="*80)
    
    if engine_results:
        print("\nEngine单独性能:")
        print(f"{'Namespace数':<15} {'程序实例数':<15} {'吞吐量(周期/秒)':<20} {'内存(MB)':<15} {'CPU(%)':<10}")
        print("-"*80)
        for result in engine_results:
            print(f"{result['namespace_count']:<15} "
                  f"{result['total_program_count']:<15} "
                  f"{result['throughput']:<20.2f} "
                  f"{result['memory_increase_mb']:<15.2f} "
                  f"{result['cpu_percent']:<10.1f}")
    
    if service_results:
        print("\nServiceManager完整性能:")
        print(f"{'Namespace数':<15} {'启动耗时(秒)':<20} {'内存(MB)':<15} {'CPU(%)':<10}")
        print("-"*80)
        for result in service_results:
            print(f"{result['namespace_count']:<15} "
                  f"{result['startup_time']:<20.4f} "
                  f"{result['memory_increase_mb']:<15.2f} "
                  f"{result['avg_cpu_percent']:<10.1f}")
    
    # 保存结果到文件
    output_file = project_root / "tools" / "performance_test_results.json"
    output_data = {
        'test_time': datetime.now().isoformat(),
        'engine_results': engine_results,
        'service_results': service_results,
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n测试结果已保存到: {output_file}")
    print("\n测试完成！")


if __name__ == "__main__":
    main()

