"""
测试查询历史数据
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))

# 直接使用只读模式连接数据库
db_path = Path(__file__).parent.parent.parent / "storage" / "storage_service.duckdb"
conn = duckdb.connect(str(db_path), read_only=True)

# 测试查询
param_name = "ns15.sin1.amplitude"
end_time = datetime.now()
start_time = end_time - timedelta(seconds=1200)

print(f"查询参数:")
print(f"  param_name: {param_name}")
print(f"  start_time: {start_time} (类型: {type(start_time)})")
print(f"  end_time: {end_time} (类型: {type(end_time)})")
print()

# 检查数据库中的时间范围
result = conn.execute(
    "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM data_records WHERE param_name = ?",
    [param_name]
).fetchone()

if result[0] > 0:
    print(f"数据库中的时间范围:")
    print(f"  记录数: {result[0]}")
    print(f"  最早时间: {result[1]} (类型: {type(result[1])})")
    print(f"  最晚时间: {result[2]} (类型: {type(result[2])})")
    print(f"\n查询时间范围:")
    print(f"  start_time: {start_time} (类型: {type(start_time)})")
    print(f"  end_time: {end_time} (类型: {type(end_time)})")
    
    # 检查时间是否在范围内
    min_ts = result[1]
    max_ts = result[2]
    if isinstance(min_ts, datetime):
        print(f"\n时间比较:")
        print(f"  start_time >= min_ts: {start_time >= min_ts}")
        print(f"  end_time <= max_ts: {end_time <= max_ts}")
        print(f"  start_time <= max_ts: {start_time <= max_ts}")
        print(f"  end_time >= min_ts: {end_time >= min_ts}")
    
    # 尝试直接查询
    print(f"\n尝试直接查询:")
    sql = """
        SELECT COUNT(*) 
        FROM data_records 
        WHERE param_name = ? 
          AND timestamp >= ? 
          AND timestamp <= ?
    """
    count = conn.execute(sql, [param_name, start_time, end_time]).fetchone()[0]
    print(f"  直接查询结果: {count} 条记录")
    
    # 尝试不限制时间范围
    sql2 = """
        SELECT COUNT(*) 
        FROM data_records 
        WHERE param_name = ?
    """
    total_count = conn.execute(sql2, [param_name]).fetchone()[0]
    print(f"  总记录数: {total_count}")
    
    # 尝试查询最近的数据
    sql3 = """
        SELECT timestamp, param_value 
        FROM data_records 
        WHERE param_name = ?
        ORDER BY timestamp DESC
        LIMIT 5
    """
    recent = conn.execute(sql3, [param_name]).fetchall()
    print(f"\n最近5条记录:")
    for row in recent:
        print(f"  {row[0]} -> {row[1]}")
else:
    print(f"参数 {param_name} 在数据库中无数据")

conn.close()
