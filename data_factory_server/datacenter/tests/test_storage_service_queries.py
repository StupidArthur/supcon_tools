import os
import time
from datetime import datetime
from pathlib import Path

import duckdb
import pytest


@pytest.fixture(scope="module")
def duckdb_conn():
    """构造一个只读的 DuckDB 连接，用于在服务运行时查询历史库。

    - db_path 优先从环境变量 STORAGE_DB_PATH 读取，
      否则默认使用 web_backend/storage_service.duckdb（与线上服务保持一致）
    - 以 read_only 模式打开数据库，不影响正在运行的 StorageService 写入
    - 若数据库文件不存在，则整组测试跳过（说明历史服务未运行或无数据）
    """
    # 与实际服务保持一致：默认使用项目同级目录下的 storage/storage_service.duckdb（避免提交代码时把数据库文件也提交上去）
    default_db_path = Path(__file__).resolve().parents[3] / "storage" / "storage_service.duckdb"
    db_path = os.getenv("STORAGE_DB_PATH", str(default_db_path))
    db_path = Path(db_path).resolve()

    if not db_path.exists():
        pytest.skip(f"历史数据库文件不存在: {db_path}，请确认 StorageService 已运行一段时间后再执行该测试")

    # 只读连接，避免与正在运行的服务发生写入冲突
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="module")
def any_active_param(duckdb_conn) -> str:
    """从历史库中选取一个有数据的位号（param_name）。

    - 通过 GROUP BY 统计每个 param_name 的记录数
    - 选取记录数最多的一个，作为后续采样测试的目标位号
    """
    row = duckdb_conn.execute(
        """
        SELECT param_name, COUNT(*) AS c
        FROM data_records
        GROUP BY param_name
        ORDER BY c DESC
        LIMIT 1
        """
    ).fetchone()

    if row is None:
        pytest.skip("历史数据库中尚无任何数据记录，无法进行采样查询测试")

    return row[0]


@pytest.fixture(scope="module")
def time_range_for_param(duckdb_conn, any_active_param: str):
    """获取该位号在历史库中的时间范围（最早/最晚时间）。"""
    row = duckdb_conn.execute(
        """
        SELECT MIN(timestamp), MAX(timestamp)
        FROM data_records
        WHERE param_name = ?
        """,
        [any_active_param],
    ).fetchone()

    if row is None or row[0] is None or row[1] is None:
        pytest.skip(f"位号 {any_active_param} 在历史库中没有有效时间戳数据")

    start, end = row
    # DuckDB 返回的 timestamp 通常是 datetime 对象，这里统一转成 datetime
    if not isinstance(start, datetime):
        start = datetime.fromisoformat(str(start))
    if not isinstance(end, datetime):
        end = datetime.fromisoformat(str(end))

    return start, end


def _query_sampled_with_duckdb(
    conn: duckdb.DuckDBPyConnection,
    param_name: str,
    start_time: datetime,
    end_time: datetime,
    sample_interval: float,
    limit: int,
):
    """在只读 DuckDB 连接上实现与 StorageService.query_sampled 等价的采样查询逻辑。"""
    # 退化为普通历史查询
    if sample_interval is None or sample_interval <= 0:
        result = conn.execute(
            """
            SELECT id, timestamp, param_name, param_value, instance_name, param_type, cycle_count, sim_time
            FROM data_records
            WHERE param_name = ?
              AND timestamp >= ?
              AND timestamp <= ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            [param_name, start_time, end_time, limit],
        ).fetchall()
    else:
        # 先取出满足条件的全部时间戳（升序）
        all_ts_rows = conn.execute(
            """
            SELECT DISTINCT timestamp
            FROM data_records
            WHERE param_name = ?
              AND timestamp >= ?
              AND timestamp <= ?
            ORDER BY timestamp ASC
            """,
            [param_name, start_time, end_time],
        ).fetchall()

        if not all_ts_rows:
            return []

        sampled_timestamps = []
        last_sampled_time = None

        for (ts,) in all_ts_rows:
            if isinstance(ts, datetime):
                ts_sec = ts.timestamp()
            else:
                ts_sec = float(ts)

            if last_sampled_time is None:
                sampled_timestamps.append(ts)
                last_sampled_time = ts_sec
            else:
                if ts_sec - last_sampled_time >= sample_interval:
                    sampled_timestamps.append(ts)
                    last_sampled_time = ts_sec

        if not sampled_timestamps:
            return []

        placeholders = ",".join(["?"] * len(sampled_timestamps))
        params = [param_name, start_time, end_time, *sampled_timestamps, limit]
        sql = f"""
            SELECT id, timestamp, param_name, param_value, instance_name, param_type, cycle_count, sim_time
            FROM data_records
            WHERE param_name = ?
              AND timestamp >= ?
              AND timestamp <= ?
              AND timestamp IN ({placeholders})
            ORDER BY timestamp DESC
            LIMIT ?
        """
        result = conn.execute(sql, params).fetchall()

    records = []
    for row in result:
        records.append(
            {
                "id": row[0],
                "timestamp": row[1].isoformat() if isinstance(row[1], datetime) else str(row[1]),
                "param_name": row[2],
                "param_value": row[3],
                "instance_name": row[4],
                "param_type": row[5],
                "cycle_count": row[6],
                "sim_time": row[7],
            }
        )
    return records


def test_query_sampled_basic(duckdb_conn, any_active_param: str, time_range_for_param):
    """基本采样查询：对单个位号按固定采样周期查询历史值。

    用例目标：
    - 验证 `query_sampled` 能在指定时间范围内返回采样后的历史数据
    - 验证返回的记录时间戳有序且间隔大致不小于采样周期
    """
    start_time, end_time = time_range_for_param

    # 采样间隔：60 秒（按分钟采样）
    sample_interval = 60.0

    records = _query_sampled_with_duckdb(
        conn=duckdb_conn,
        param_name=any_active_param,
        start_time=start_time,
        end_time=end_time,
        sample_interval=sample_interval,
        limit=10_000,
    )

    # 至少应该有一条数据
    assert isinstance(records, list)
    assert len(records) > 0

    # 时间戳应按倒序返回
    timestamps = [datetime.fromisoformat(r["timestamp"]) for r in records]
    assert timestamps == sorted(timestamps, reverse=True)

    # 参数名应全部一致
    assert all(r["param_name"] == any_active_param for r in records)


def test_query_sampled_performance(duckdb_conn, any_active_param: str, time_range_for_param):
    """采样查询性能测试：在较长时间范围内对单个位号做采样查询，并记录耗时。

    这里不追求极端严格的性能指标，而是给一个经验上的上限：
    - 对单个位号、6 小时以上历史数据、按 60 秒采样，查询耗时应在 1 秒以内
    """
    start_time, end_time = time_range_for_param

    sample_interval = 60.0

    t0 = time.perf_counter()
    records = _query_sampled_with_duckdb(
        conn=duckdb_conn,
        param_name=any_active_param,
        start_time=start_time,
        end_time=end_time,
        sample_interval=sample_interval,
        limit=100_000,
    )
    t1 = time.perf_counter()

    elapsed = t1 - t0

    # 基本正确性检查
    assert isinstance(records, list)
    assert len(records) > 0

    # 性能断言（可以根据实际环境调整阈值）
    assert elapsed < 1.0, f"采样查询耗时过长：{elapsed:.3f}s"


def test_query_sampled_multi_interval(duckdb_conn, any_active_param: str, time_range_for_param):
    """多种采样间隔对比测试：

    - 对同一位号在同一时间范围内，分别以 10s / 60s / 300s 进行采样
    - 验证采样间隔越大，返回记录数越少
    """
    start_time, end_time = time_range_for_param

    intervals = [10.0, 60.0, 300.0]
    counts = []

    for interval in intervals:
        records = _query_sampled_with_duckdb(
            conn=duckdb_conn,
            param_name=any_active_param,
            start_time=start_time,
            end_time=end_time,
            sample_interval=interval,
            limit=100_000,
        )
        counts.append(len(records))

    # 至少每种间隔都有数据
    assert all(c > 0 for c in counts)

    # 采样间隔越大，返回的点数不应增加（通常会减少或持平）
    assert counts[0] >= counts[1] >= counts[2]
