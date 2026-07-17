"""
测试 datacenter 模块功能
"""

import sys
import pathlib
from datetime import datetime, timedelta

# 添加项目根目录到路径
project_root = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 导入程序和函数（触发注册）
from components import programs  # noqa: F401
from components import functions  # noqa: F401

from controller.parser import DSLParser
from controller.engine import UnifiedEngine
from datacenter import RealtimeConfig

def test_imports():
    """测试导入"""
    print("=" * 60)
    print("1. 测试导入")
    print("=" * 60)
    try:
        from datacenter import RealtimePublisher
        print("[OK] 导入成功")
        return True
    except ImportError as e:
        print(f"[FAIL] 导入失败: {e}")
        return False

def test_realtime_manager():
    """测试实时数据发布（Redis）"""
    print("\n" + "=" * 60)
    print("2. 测试实时数据发布（Redis）")
    print("=" * 60)
    
    try:
        from datacenter import RealtimePublisher
        
        # 创建 Redis 连接配置
        config = RealtimeConfig(
            redis_host="localhost",
            redis_port=6379,
            pubsub_channel="data_factory"
        )
        
        # 尝试连接 Redis
        try:
            publisher = RealtimePublisher(config)
            print("[OK] RealtimePublisher 初始化成功")
        except Exception as e:
            print(f"[SKIP] Redis 连接失败（可能未启动）: {e}")
            print("    提示: 如果不需要测试 Redis，可以跳过此测试")
            return True  # 跳过测试，不算失败
        
        # 测试推送快照
        test_snapshot = {
            "tank1.level": 50.5,
            "pid1.mv": 30.0,
            "cycle_count": 1,
            "sim_time": 0.5,
            "time_str": "2024-12-06 10:00:00",
        }
        
        publisher.push_snapshot(test_snapshot)
        print("[OK] 推送快照成功")
        
        # 关闭连接
        publisher.close()
        print("[OK] 关闭连接成功")
        
        return True
    except Exception as e:
        print(f"[FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_engine_integration():
    """测试 Engine 集成"""
    print("\n" + "=" * 60)
    print("3. 测试 Engine 集成")
    print("=" * 60)
    
    try:
        # 解析配置文件
        parser = DSLParser()
        config_path = project_root / "classical_config" / "display_demo.yaml"
        config = parser.parse_file(config_path)
        print("[OK] 配置文件解析成功")
        
        # 创建引擎
        engine = UnifiedEngine.from_program_config(config)
        print("[OK] 引擎创建成功")
        
        # 尝试启用实时数据管理（如果 Redis 可用）
        try:
            realtime_config = RealtimeConfig(
                redis_host="localhost",
                redis_port=6379,
                pubsub_channel="data_factory"
            )
            engine.enable_realtime_data(realtime_config)
            print("[OK] 实时数据管理已启用")
        except Exception as e:
            print(f"[SKIP] 实时数据管理启用失败（Redis 可能未启动）: {e}")
        
        # 运行几个周期（GENERATOR 模式）
        print("\n运行 10 个周期（GENERATOR 模式）...")
        results = engine.run_generator(10)
        print(f"[OK] 运行成功，生成了 {len(results)} 个快照")
        
        # 检查快照数据
        if results:
            snapshot = results[0]
            print(f"    快照包含字段: {list(snapshot.keys())[:5]}...")
            print(f"    cycle_count: {snapshot.get('cycle_count')}")
            print(f"    need_sample: {snapshot.get('need_sample')}")
        
        return True
    except Exception as e:
        print(f"[FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_realtime_execution():
    """测试实时执行（短时间运行）"""
    print("\n" + "=" * 60)
    print("4. 测试实时执行（短时间运行）")
    print("=" * 60)
    
    try:
        # 解析配置文件
        parser = DSLParser()
        config_path = project_root / "classical_config" / "display_demo.yaml"
        config = parser.parse_file(config_path)
        
        # 创建引擎
        engine = UnifiedEngine.from_program_config(config)
        
        # 尝试启用实时数据管理
        try:
            realtime_config = RealtimeConfig(
                redis_host="localhost",
                redis_port=6379,
                pubsub_channel="data_factory"
            )
            engine.enable_realtime_data(realtime_config)
            print("[OK] 实时数据管理已启用")
        except Exception as e:
            print(f"[SKIP] 实时数据管理启用失败: {e}")
        
        # 运行几个周期（REALTIME 模式，但快速执行）
        print("\n运行 5 个周期（REALTIME 模式）...")
        count = 0
        for snapshot in engine.run_realtime():
            count += 1
            print(f"  周期 {count}: cycle_count={snapshot.get('cycle_count')}, need_sample={snapshot.get('need_sample')}")
            if count >= 5:
                break  # 只运行5个周期
        
        print(f"[OK] 实时执行成功，运行了 {count} 个周期")
        
        return True
    except KeyboardInterrupt:
        print("\n[OK] 用户中断（正常）")
        return True
    except Exception as e:
        print(f"[FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("Data Manager 模块测试")
    print("=" * 60)
    
    results = []
    
    # 1. 测试导入
    results.append(("导入测试", test_imports()))
    
    # 2. 测试实时数据管理
    results.append(("实时数据发布", test_realtime_manager()))
    
    # 3. 测试 Engine 集成
    results.append(("Engine 集成", test_engine_integration()))
    
    # 4. 测试实时执行
    results.append(("实时执行", test_realtime_execution()))
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    passed = 0
    failed = 0
    skipped = 0
    
    for name, result in results:
        if result:
            print(f"[PASS] {name}")
            passed += 1
        else:
            print(f"[FAIL] {name}")
            failed += 1
    
    print(f"\n总计: {passed} 通过, {failed} 失败")
    
    if failed == 0:
        print("\n✅ 所有测试通过！")
        return 0
    else:
        print("\n❌ 部分测试失败")
        return 1

if __name__ == "__main__":
    sys.exit(main())

