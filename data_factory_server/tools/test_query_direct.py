"""
直接测试历史数据查询
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))

# 测试查询参数（与前端发送的一致）
param_name = "ns14.sin1.out"
end_time_str = "2025-12-19T05:28:05.315Z"
time_length = 1200
sample_points = 1200

print(f"测试查询参数:")
print(f"  param_name: {param_name}")
print(f"  end_time: {end_time_str}")
print(f"  time_length: {time_length}")
print(f"  sample_points: {sample_points}")
print()

# 解析时间（与web_backend/main.py中的逻辑一致）
try:
    # 处理Z时区标识
    end_time_str_parsed = end_time_str.replace('Z', '+00:00')
    end_time = datetime.fromisoformat(end_time_str_parsed)
    
    print(f"解析UTC时间: {end_time} (时区: {end_time.tzinfo})")
    
    # 如果datetime有时区信息，转换为本地时间（naive datetime）
    if end_time.tzinfo is not None:
        end_time_local = end_time.astimezone().replace(tzinfo=None)
        print(f"转换为本地时间: {end_time_local} (类型: {type(end_time_local)})")
        end_time = end_time_local
    
    start_time = end_time - timedelta(seconds=time_length)
    
    # 计算采样间隔
    if sample_points > 1:
        sample_interval = time_length / (sample_points - 1)
    else:
        sample_interval = time_length
    
    print(f"解析后的时间:")
    print(f"  start_time: {start_time} (类型: {type(start_time)})")
    print(f"  end_time: {end_time} (类型: {type(end_time)})")
    print(f"  sample_interval: {sample_interval}")
    print()
    
    # 连接数据库
    db_path = Path(__file__).parent.parent.parent / "storage" / "storage_service.duckdb"
    if not db_path.exists():
        print(f"错误: 数据库文件不存在: {db_path}")
        sys.exit(1)
    
    print(f"连接数据库: {db_path}")
    conn = duckdb.connect(str(db_path), read_only=True)
    
    # 先检查数据库中是否有该参数的数据
    check_result = conn.execute(
        "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM data_records WHERE param_name = ?",
        [param_name]
    ).fetchone()
    
    if check_result and check_result[0] > 0:
        count, min_ts, max_ts = check_result
        print(f"数据库中的时间范围:")
        print(f"  记录数: {count}")
        print(f"  最早时间: {min_ts} (类型: {type(min_ts)})")
        print(f"  最晚时间: {max_ts} (类型: {type(max_ts)})")
        print()
        
        # 检查时间范围
        if isinstance(min_ts, datetime):
            print(f"时间比较:")
            print(f"  start_time >= min_ts: {start_time >= min_ts}")
            print(f"  end_time <= max_ts: {end_time <= max_ts}")
            print(f"  start_time <= max_ts: {start_time <= max_ts}")
            print(f"  end_time >= min_ts: {end_time >= min_ts}")
            print()
            
            # 计算时间差
            if start_time < min_ts:
                print(f"  警告: start_time ({start_time}) 早于数据库最早时间 ({min_ts})")
                print(f"  时间差: {(min_ts - start_time).total_seconds()} 秒")
            if end_time > max_ts:
                print(f"  警告: end_time ({end_time}) 晚于数据库最晚时间 ({max_ts})")
                print(f"  时间差: {(end_time - max_ts).total_seconds()} 秒")
            print()
    else:
        print(f"警告: 参数 {param_name} 在数据库中无数据")
        print()
        conn.close()
        sys.exit(1)
    
    # 执行查询（模拟query_sampled的逻辑）
    print("执行查询...")
    
    # 第一步：查询所有满足条件的时间戳
    sql = """
        SELECT DISTINCT timestamp
        FROM data_records
        WHERE param_name = ?
          AND timestamp >= ?
          AND timestamp <= ?
        ORDER BY timestamp ASC
    """
    print(f"SQL: {sql}")
    print(f"参数: param_name={param_name}, start_time={start_time}, end_time={end_time}")
    
    all_timestamps = conn.execute(sql, [param_name, start_time, end_time]).fetchall()
    print(f"查询到 {len(all_timestamps)} 个时间戳")
    
    if len(all_timestamps) == 0:
        print("未查询到时间戳，尝试不限制时间范围...")
        sql2 = """
            SELECT DISTINCT timestamp
            FROM data_records
            WHERE param_name = ?
            ORDER BY timestamp ASC
            LIMIT 10
        """
        all_timestamps2 = conn.execute(sql2, [param_name]).fetchall()
        print(f"不限制时间范围查询到 {len(all_timestamps2)} 个时间戳")
        if all_timestamps2:
            print(f"最近的时间戳: {all_timestamps2[-1][0]}")
    
    # 第二步：采样
    sampled_timestamps = []
    last_sampled_time = None
    
    for row in all_timestamps:
        ts = row[0]
        if isinstance(ts, datetime):
            ts_timestamp = ts.timestamp()
        else:
            ts_timestamp = float(ts)
        
        if last_sampled_time is None:
            sampled_timestamps.append(ts)
            last_sampled_time = ts_timestamp
        else:
            time_diff = ts_timestamp - last_sampled_time
            if time_diff >= sample_interval:
                sampled_timestamps.append(ts)
                last_sampled_time = ts_timestamp
    
    print(f"采样后得到 {len(sampled_timestamps)} 个时间戳")
    
    # 第三步：查询实际数据
    if sampled_timestamps:
        placeholders = ",".join(["?"] * len(sampled_timestamps))
        sql3 = f"""
            SELECT id, timestamp, param_name, param_value, instance_name, param_type, cycle_count, sim_time
            FROM data_records
            WHERE param_name = ?
              AND timestamp >= ?
              AND timestamp <= ?
              AND timestamp IN ({placeholders})
            ORDER BY timestamp DESC
            LIMIT ?
        """
        params = [param_name, start_time, end_time, *sampled_timestamps, sample_points * 2]
        records = conn.execute(sql3, params).fetchall()
        
        print(f"最终查询结果: {len(records)} 条记录")
        
        if records:
            print(f"第一条记录: timestamp={records[0][1]}, value={records[0][3]}")
            print(f"最后一条记录: timestamp={records[-1][1]}, value={records[-1][3]}")
        else:
            print("未查询到数据")
    else:
        print("采样后没有时间戳，无法查询数据")
    
    conn.close()
    
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
