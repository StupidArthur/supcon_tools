"""跑 N 次重连测试，输出三件事的统计（mean/median/min/max/p95）。

用法: python examples/timing_aggregate.py [--count 10]
"""

from __future__ import annotations

import argparse
import os
import statistics
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
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.wait()


def kill_orphan_mocker():
    """杀任何残留的 ua_mocker 进程，避免端口冲突。"""
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                if ":18950 " in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        pid = parts[-1]
                        try:
                            subprocess.run(
                                ["taskkill", "//F", "//PID", pid],
                                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            )
                        except Exception:
                            pass
        except Exception:
            pass
    time.sleep(2)


def poll_until(api: AlgAPI, ds_id: int, predicate, timeout_sec: int, interval: float = 1.0):
    t0 = time.monotonic()
    last = None
    while time.monotonic() - t0 < timeout_sec:
        last = query_alive(api, ds_id)
        if predicate(last):
            return time.monotonic() - t0, last
        time.sleep(interval)
    return None, last


def one_iteration(api: AlgAPI, ds_id: int, mocker_proc: subprocess.Popen) -> dict | None:
    """跑一次：kill → discover → restart → reconnect → new data。

    返回 {"discover": x, "reconnect": y, "data_gap": z} 秒。
    失败返回 None（不抛异常）。
    """
    # 记 kill 前的最后 appTime
    last_before = query_latest_app_time(api, TAG)
    if not last_before:
        time.sleep(35)
        last_before = query_latest_app_time(api, TAG)
    if not last_before:
        print(f"    [SKIP] 没有 kill 前的数据点", flush=True)
        return None

    # kill
    t_kill = time.monotonic()
    kill_mocker(mocker_proc)

    # 等发现
    elapsed, _ = poll_until(api, ds_id, lambda v: v is False, timeout_sec=120)
    if elapsed is None:
        print(f"    [FAIL] 120s 内没发现 alive=False", flush=True)
        # 尝试重启避免后续卡住
        return None
    t_alive_false = time.monotonic()
    discover_latency = t_alive_false - t_kill

    # 重启
    new_proc = start_mocker()

    # 等重连
    elapsed, _ = poll_until(api, ds_id, lambda v: v is True, timeout_sec=120)
    if elapsed is None:
        print(f"    [FAIL] 120s 内没重连", flush=True)
        kill_mocker(new_proc)
        return None
    t_alive_true = time.monotonic()
    reconnect_latency = t_alive_true - t_alive_false

    # 等新数据点
    t_data_polling = time.monotonic()
    first_after = None
    while time.monotonic() - t_data_polling < 90:
        latest_app = query_latest_app_time(api, TAG)
        if latest_app and latest_app > last_before:
            first_after = latest_app
            break
        time.sleep(2)
    if not first_after:
        print(f"    [WARN] 90s 内没找到新数据点", flush=True)
        kill_mocker(new_proc)
        return None

    data_gap = (parse_dt(first_after) - parse_dt(last_before)).total_seconds()
    kill_mocker(new_proc)
    return {
        "discover": discover_latency,
        "reconnect": reconnect_latency,
        "data_gap": data_gap,
    }


def stats(values: list[float]) -> str:
    if not values:
        return "n/a"
    sorted_v = sorted(values)
    n = len(sorted_v)
    p95_idx = min(int(n * 0.95), n - 1)
    return (
        f"n={n:>2}  "
        f"min={min(sorted_v):>5.1f}  "
        f"median={statistics.median(sorted_v):>5.1f}  "
        f"mean={statistics.mean(sorted_v):>5.1f}  "
        f"p95={sorted_v[p95_idx]:>5.1f}  "
        f"max={max(sorted_v):>5.1f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args()

    api = AlgAPI(TPT_URL, timeout=15.0)
    api.login(TPT_USER, TPT_PASSWORD)
    ds_id = find_ds_id(api)
    print(f"目标 ds_id={ds_id}, 跑 {args.count} 次", flush=True)

    kill_orphan_mocker()
    mocker_proc = start_mocker()
    time.sleep(4)
    print("起 ua_mocker，等 tpt 接通...", flush=True)
    elapsed, _ = poll_until(api, ds_id, lambda v: v is True, timeout_sec=90)
    if elapsed is None:
        print("[FATAL] 90s 内 tpt 没接通", flush=True)
        kill_mocker(mocker_proc); return 1
    print(f"✓ tpt 接通 ({elapsed:.0f}s)\n", flush=True)

    discover_l = []
    reconnect_l = []
    data_gap_l = []

    for i in range(1, args.count + 1):
        print(f"[{i}/{args.count}] running...", flush=True)
        t_start_iter = time.monotonic()
        result = one_iteration(api, ds_id, mocker_proc)
        cost = time.monotonic() - t_start_iter
        # 每次 kill 之后，mocker_proc 已经被杀死
        # 重启一个供下一轮
        mocker_proc = start_mocker()
        time.sleep(2)
        if result is None:
            print(f"  [{i}] FAILED, took {cost:.0f}s\n", flush=True)
            # 不计入统计
            continue
        discover_l.append(result["discover"])
        reconnect_l.append(result["reconnect"])
        data_gap_l.append(result["data_gap"])
        print(
            f"  [{i}] discover={result['discover']:.0f}s  "
            f"reconnect={result['reconnect']:.0f}s  "
            f"data_gap={result['data_gap']:.0f}s  "
            f"(iter took {cost:.0f}s)\n",
            flush=True,
        )

    # 清理
    kill_mocker(mocker_proc)

    print("=" * 60)
    print(f"  {args.count} 次重连测试统计")
    print("=" * 60)
    print(f"  1. server 死后客户端多久发现 alive=False:")
    print(f"     {stats(discover_l)}")
    print()
    print(f"  2. 发现后多久重连成功 alive=True:")
    print(f"     {stats(reconnect_l)}")
    print()
    print(f"  3. 数据中断多久 (appTime 差):")
    print(f"     {stats(data_gap_l)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
