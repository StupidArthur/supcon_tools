#!/usr/bin/env python3
"""生成多份"老系统导出格式"测试数据集 (迁移工具的真实输入).

用已注册的 1100 个位号名 (omc_<type>_001 ~ omc_<type>_100), 每种类型 100 个,
两两配对切 50 份, 每份 11 类型 × 2 = 22 个位号. 全部位号用上, 不重不漏.

每份是一个 xlsx, long 格式 (与平台导出一致):
  - 每 tag 1 个 sheet (sheet 名 = tag 名)
  - 4 列: Tag Time, App Time, Quality, Tag Value
  - 时间 yyyy-MM-dd HH:mm:ss (横杠), 倒序 (新→旧)
  - Tag Value 字符串 (DOUBLE/FLOAT 带 .0, INT 类无小数, BOOLEAN 0/1)
  - Quality 固定 192

默认每位号 1000 点. 生成到 data/inputs/datasets/.

直接跑: python scripts/gen_export_datasets.py
可选: --points 1000 --out-dir data/inputs/datasets
"""
import os
import sys
import argparse
from datetime import datetime, timedelta
from openpyxl import Workbook

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 11 种数据类型 (与 gen_tag_register.py 一致)
DATA_TYPES = ["BOOLEAN", "S_BYTE", "BYTE", "SHORT", "U_SHORT",
              "INT", "U_INT", "LONG", "U_LONG", "FLOAT", "DOUBLE"]

# INT 类 (无小数的字符串值): S_BYTE/BYTE/SHORT/U_SHORT/INT/U_INT/LONG/U_LONG
INT_TYPES = {"S_BYTE", "BYTE", "SHORT", "U_SHORT", "INT", "U_INT", "LONG", "U_LONG"}
FLOAT_TYPES = {"FLOAT", "DOUBLE"}  # 带 .0
# BOOLEAN: 0/1


def tag_value(dt: str, i: int) -> str:
    """第 i 个点 (0-based) 的字符串值. 与 info.md 数据规则一致: r%100 循环."""
    if dt == "BOOLEAN":
        return str(i % 2)
    r = i % 100
    if dt in FLOAT_TYPES:
        return f"{r}.0"
    return str(r)  # INT 类


def gen_one_dataset(path: str, tags: list, points: int, start: datetime, freq_sec: int):
    """生成一份 xlsx. tags: [(tagName, dataType), ...]. 每位号 points 个点."""
    wb = Workbook()
    wb.remove(wb.active)  # 删默认 sheet
    for tag_name, dt in tags:
        ws = wb.create_sheet(title=tag_name)
        ws.append(["Tag Time", "App Time", "Quality", "Tag Value"])
        # 倒序: 最新在前. i=0 是最新点 (points-1 的值), i=points-1 是最旧点 (0 的值)
        for i in range(points):
            # 时间: 第 i 行 = start + (points-1-i)*freq  (最新点在最前)
            t = start + timedelta(seconds=(points - 1 - i) * freq_sec)
            ts = t.strftime("%Y-%m-%d %H:%M:%S")
            ws.append([ts, ts, 192, tag_value(dt, points - 1 - i)])
    wb.save(path)


def main():
    ap = argparse.ArgumentParser(description="生成多份导出格式测试数据集")
    ap.add_argument("--points", type=int, default=1000, help="每位号数据点数 (默认 1000)")
    ap.add_argument("--per-type", type=int, default=2, help="每份每种类型几个位号 (默认 2)")
    ap.add_argument("--freq", type=int, default=10, help="采样周期秒 (默认 10)")
    ap.add_argument("--out-dir", default="data/inputs/datasets", help="输出目录")
    ap.add_argument("--prefix", default="omc", help="位号名前缀")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    # 每种类型 100 个位号, 按 per_type 切份: 100 / per_type 份
    n_per_type = 100
    n_files = n_per_type // args.per_type
    print(f"[生成] {n_files} 份, 每份 {len(DATA_TYPES)} 类型 × {args.per_type} = "
          f"{len(DATA_TYPES) * args.per_type} 位号, 每位号 {args.points} 点")

    # 每份的起始时间错开, 避免不同份时间重叠 (便于回查验证)
    base_start = datetime(2026, 1, 1, 0, 0, 0)
    span_sec = args.points * args.freq  # 一份的时间跨度
    for fidx in range(n_files):
        tags = []
        for dt in DATA_TYPES:
            low = dt.lower()
            for k in range(args.per_type):
                num = fidx * args.per_type + k + 1  # 1..100
                tags.append((f"{args.prefix}_{low}_{num:03d}", dt))
        start = base_start + timedelta(seconds=fidx * span_sec)
        out = os.path.join(args.out_dir, f"dataset_{fidx + 1:02d}.xlsx")
        gen_one_dataset(out, tags, args.points, start, args.freq)
        print(f"  [{fidx + 1:02d}/{n_files}] {out}  ({len(tags)} 位号, "
              f"{start.strftime('%Y-%m-%d %H:%M:%S')} 起)")

    print(f"[完成] {n_files} 份已生成到 {args.out_dir}/")


if __name__ == "__main__":
    main()
