"""
检查数据库中是否有指定参数的数据
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb

# 检查两个可能的路径
db_path1 = Path(__file__).parent.parent / "storage" / "storage_service.duckdb"
db_path2 = Path(__file__).parent.parent.parent / "storage" / "storage_service.duckdb"

db_path = None
if db_path1.exists():
    db_path = db_path1
elif db_path2.exists():
    db_path = db_path2
else:
    print(f"数据库文件不存在，检查的路径:")
    print(f"  1. {db_path1}")
    print(f"  2. {db_path2}")
    exit(1)

print(f"使用数据库: {db_path}")

conn = duckdb.connect(str(db_path))

# 检查参数 ns15.sin1.amplitude
param_name = "ns15.sin1.amplitude"
result = conn.execute(
    "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM data_records WHERE param_name = ?",
    [param_name]
).fetchone()

if result[0] > 0:
    print(f"参数 {param_name}:")
    print(f"  记录数: {result[0]}")
    print(f"  时间范围: {result[1]} 到 {result[2]}")
else:
    print(f"参数 {param_name}: 无数据")
    
    # 检查是否有类似参数
    similar = conn.execute(
        "SELECT DISTINCT param_name FROM data_records WHERE param_name LIKE ? LIMIT 10",
        [f"%ns15.sin1%"]
    ).fetchall()
    
    if similar:
        print(f"\n找到类似的参数:")
        for row in similar:
            print(f"  - {row[0]}")
    else:
        print(f"\n未找到包含 'ns15.sin1' 的参数")

# 检查所有参数的数量
all_params = conn.execute(
    "SELECT param_name, COUNT(*) as cnt FROM data_records GROUP BY param_name ORDER BY cnt DESC LIMIT 10"
).fetchall()

print(f"\n数据库中参数统计（前10个）:")
for row in all_params:
    print(f"  {row[0]}: {row[1]} 条记录")

conn.close()

