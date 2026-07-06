#!/usr/bin/env python3
"""生成位号注册 xlsx (给平台批量导入建位号用).

每种数据类型 100 个位号, 共 11 种 = 1100 行. 数据源 OMC117.
生成后在平台"位号管理"页用导入功能上传即可.

直接跑: python scripts/gen_tag_register.py
可选参数: python scripts/gen_tag_register.py --prefix omc --count 100 --ds OMC117 --out tag_register.xlsx
"""
import os
import argparse
from openpyxl import Workbook

# 11 种数据类型 (与平台 dataType 1~11 对应)
DATA_TYPES = ["BOOLEAN", "S_BYTE", "BYTE", "SHORT", "U_SHORT",
              "INT", "U_INT", "LONG", "U_LONG", "FLOAT", "DOUBLE"]

# 平台导入模板表头 (与 data/samples/all_type.xlsx 一致, 21 列)
HEADERS = [
    "系统位号名", "底层位号名", "位号类型", "数据源名称（一次位号）", "单位",
    "数据类型", "取值表达式（二次位号）", "位号值（虚位号）", "采集频率",
    "位号值高限", "位号值高高限", "位号值高高高限", "位号值低限", "位号值低低限", "位号值低低低限",
    "描述", "节点名", "是否需要推送", "是否只读", "量程下限", "量程上限",
]


def main():
    ap = argparse.ArgumentParser(description="生成位号注册 xlsx")
    ap.add_argument("--prefix", default="omc", help="位号名前缀 (默认 omc)")
    ap.add_argument("--count", type=int, default=100, help="每种类型个数 (默认 100)")
    ap.add_argument("--ds", default="OMC117", help="数据源名称 (默认 OMC117)")
    ap.add_argument("--node", default="Root", help="节点名 (默认 Root)")
    ap.add_argument("--out", default="tag_register.xlsx", help="输出文件名")
    args = ap.parse_args()

    wb = Workbook()
    ws = wb.active
    ws.title = "sheet1"
    ws.append(HEADERS)

    total = 0
    for dt in DATA_TYPES:
        # 位号名: omc_float_001 ... omc_float_100
        low = dt.lower()
        for i in range(1, args.count + 1):
            name = f"{args.prefix}_{low}_{i:03d}"
            ws.append([
                name,              # 系统位号名
                name,              # 底层位号名
                "一次位号",         # 位号类型
                args.ds,           # 数据源名称
                "",                # 单位
                dt,                # 数据类型
                None,              # 取值表达式
                None,              # 位号值
                10,                # 采集频率
                None, None, None, None, None, None,  # 各限值
                f"{name} 描述",    # 描述
                args.node,         # 节点名
                "true",            # 是否需要推送
                "false",           # 是否只读
                None, None,        # 量程下限/上限
            ])
            total += 1

    wb.save(args.out)
    print(f"[生成] {args.out}")
    print(f"  {len(DATA_TYPES)} 种类型 × {args.count} 个 = {total} 行")
    print(f"  数据源: {args.ds}, 节点: {args.node}, 前缀: {args.prefix}")
    print(f"  位号名例: {args.prefix}_{DATA_TYPES[0].lower()}_001 ... {args.prefix}_{DATA_TYPES[0].lower()}_{args.count:03d}")


if __name__ == "__main__":
    main()
