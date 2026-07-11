"""三个独立时间测量：

1. server 死后，tpt 客户端多久发现（alive 翻 False）
2. 发现后，多久重连成功（alive 翻回 True）—— 用户的"30s 周期"在这里
3. 数据实际中断多久（从最后一个 kill 前的数据点 appTime，到 reconnect 后第一个新数据点 appTime）

所有时间点用 1s 轮询精确捕获。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tpt_api import AlgAPI
from tpt_api import datahub as dh_mod

TPT_URL = "http://10.10.58.153:31501"
TPT_USER = "admin"
TPT_PASSWORD = "123456"
OPCUA_PUBLIC_HOST = "10.30.70.77"
MOCKER_SCRIPT = r"F:\github\supcon_tools\ua_mocker\main.py"
MOCKER_YAML = r"F:\github\supcon_tools\ua_tpt_loop\examples\tiny_mocker_config.yaml"
DS_NAME_HINT = "mocker_10.30.70.77_18950"
TAG = "1_loop_demo_1"


def banner(msg: str) -> None:
    print(f"\n{'='*60}\n  {msg}\n{'='*60}")


def find_ds_id(api: AlgAPI) -> int:
    for ds in dh_mod.get_all_ds_info(api):
        if ds.get("dsName") == DS_NAME_HINT:
            return ds["id"]
    raise RuntimeError(f"未找到 {DS_NAME_HINT}")


def query_alive(api: AlgAPI, ds_id: int):
    for ds in dh_mod.get_all_ds_info(api):
        if ds["id"] == ds_id:
            return ds.get("alive")
    return None


def query_latest_app_time(api: AlgAPI, tag: str) -> str | None:
    """查最近 5 分钟内该 tag 的最新数据点 appTime（没有则 None）。"""
    end = datetime.now() + timedelta(seconds=5)
    beg = end - timedelta(minutes=5)
    hist = dh_mod.get_all_history(
        api, [tag],
        beg.strftime("%Y-%m-%d %H:%M:%S"),
        end.strftime("%Y-%m-%d %H:%M:%S"),
        page_size=10,
    )
    if hist.get(tag):
        return hist[tag][0].get("appTime")
    return None


def parse_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def start_mocker() -> subprocess.Popen:
    return subprocess.Popen(
        ["python", MOCKER_SCRIPT, MOCKER_YAML],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def kill_mocker(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.wait()


def poll_until(api: AlgAPI, ds_id: int, predicate, timeout_sec: int, interval: float = 1.0):
    """轮询 alive 直到 predicate(alive) 为 True，返回 (达到时刻秒, 实际值)。"""
    t0 = time.monotonic()
    last = None
    while time.monotonic() - t0 < timeout_sec:
        last = query_alive(api, ds_id)
        if predicate(last):
            return time.monotonic() - t0, last
        time.sleep(interval)
    return None, last


def main() -> int:
    api = AlgAPI(TPT_URL, timeout=15.0)
    api.login(TPT_USER, TPT_PASSWORD)
    ds_id = find_ds_id(api)
    print(f"目标 ds_id={ds_id}")

    # === 起 ua_mocker，等 tpt 标 alive=True ===
    banner("准备：起 ua_mocker，等 tpt 接通")
    proc = start_mocker()
    time.sleep(4)
    elapsed, _ = poll_until(api, ds_id, lambda v: v is True, timeout_sec=90)
    if elapsed is None:
        print("  [FAIL] 90s 内 tpt 没标 alive")
        kill_mocker(proc); return 1
    print(f"  ✓ tpt 标 alive=True ({elapsed:.0f}s)")

    # === 测 3. 数据中断：记录 kill 前的最后数据点 appTime ===
    banner("T0: 记录 kill 前的最后数据点 appTime")
    last_before = query_latest_app_time(api, TAG)
    print(f"  1_loop_demo_1 最后数据点 appTime = {last_before}")
    if not last_before:
        print("  [WARN] kill 前没数据点，先等 30s 让 tpt 采到")
        time.sleep(35)
        last_before = query_latest_app_time(api, TAG)
        print(f"  重试后: {last_before}")

    # === 测 1. server 死后，客户端多久发现 ===
    banner("测 1: kill server，记录 T_alive_false")
    t_kill = time.monotonic()
    kill_mocker(proc)
    elapsed, _ = poll_until(api, ds_id, lambda v: v is False, timeout_sec=120)
    t_alive_false = time.monotonic()
    if elapsed is None:
        print("  [FAIL] 120s 内没看到 alive=False")
        return 1
    print(f"  ✓ tpt 发现 alive=False 用时 {elapsed:.0f}s")
    discover_latency = t_alive_false - t_kill

    # === 测 2. 发现后，多久重连成功 ===
    banner("测 2: 重启 ua_mocker，记录 T_alive_true（30s 周期在这里体现）")
    proc2 = start_mocker()
    t_restart = time.monotonic()
    elapsed, _ = poll_until(api, ds_id, lambda v: v is True, timeout_sec=120)
    t_alive_true = time.monotonic()
    if elapsed is None:
        print("  [FAIL] 120s 内没重连")
        kill_mocker(proc2); return 1
    print(f"  ✓ tpt 重连成功用时 {elapsed:.0f}s（从 restart 算）")
    print(f"  ✓ tpt 重连成功用时 {t_alive_true - t_alive_false:.0f}s（从发现 alive=False 算）← 你问的 #2")
    reconnect_after_discover = t_alive_true - t_alive_false

    # === 测 3. 数据中断多久（接续）===
    banner("测 3: 轮询新数据点，记录 T_first_data_after")
    t_data_polling = time.monotonic()
    first_after = None
    while time.monotonic() - t_data_polling < 90:
        latest_app = query_latest_app_time(api, TAG)
        if latest_app and last_before and latest_app > last_before:
            # 找到了比 kill 前更新的点
            first_after = latest_app
            t_found = time.monotonic()
            break
        time.sleep(2)
    else:
        t_found = None

    if first_after:
        gap_seconds = (parse_dt(first_after) - parse_dt(last_before)).total_seconds()
        print(f"  ✓ 新数据点 appTime = {first_after}")
        print(f"  ✓ 数据中断 = {gap_seconds:.0f}s（{last_before} → {first_after}）")
    else:
        print("  [WARN] 90s 内没找到新数据点")

    # 清理
    kill_mocker(proc2)

    # === 总结 ===
    banner("三件事的精确测量")
    print(f"  事件时间线（相对 t_kill = 0s）:")
    print(f"    t_kill         =    0s   server 死")
    print(f"    t_alive_false  = {discover_latency:>4.0f}s   tpt 客户端发现 (#1)")
    print(f"    t_restart      = {t_restart - t_kill:>4.0f}s   server 重启")
    print(f"    t_alive_true   = {t_alive_true - t_kill:>4.0f}s   tpt 重连成功 (#2 = {reconnect_after_discover:.0f}s 从发现算)")
    if first_after:
        print(f"    t_first_data   = {t_found - t_kill:>4.0f}s   第一个新数据点入库 (#3)")
        print()
        print(f"  答你的三个问题:")
        print(f"    1. 客户端多久发现:  {discover_latency:.0f}s")
        print(f"    2. 发现后多久重连:  {reconnect_after_discover:.0f}s")
        print(f"    3. 数据中断多久:    {gap_seconds:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
