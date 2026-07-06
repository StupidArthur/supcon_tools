import _path_helper  # noqa: 帮脚本 import 根目录的模块

#!/usr/bin/env python3
"""
主脚本: 平台导出 xlsx → 平台导入 xlsx.

用法:
  python convert_export_to_import.py --input export_data.xlsx --output history_for_import.xlsx
  python convert_export_to_import.py --input export_data.xlsx --output history_for_import.xlsx --upload
"""
import argparse

from xlsx_io import read_all_sheets, write_wide_xlsx
from convert import convert_export_to_wide_input


def main():
    parser = argparse.ArgumentParser(description="导出 xlsx → 导入 xlsx 转换")
    parser.add_argument("--input", required=True, help="导出的 xlsx 路径")
    parser.add_argument("--output", required=True, help="转换后用于导入的 xlsx 路径")
    parser.add_argument("--upload", action="store_true", help="转换后直接调 API 上传")
    args = parser.parse_args()

    # 1. 读导出 (xlsx_io 负责, 数据是 list/dict)
    print(f"[1/3] 读 {args.input} ...")
    sheets = read_all_sheets(args.input)
    print(f"  sheet 数: {len(sheets)}")
    print(f"  tag 列表: {list(sheets.keys())}")

    # 2. 转换 (convert 模块, 纯数据)
    print(f"\n[2/3] 格式转换 long → wide ...")
    out = convert_export_to_wide_input(sheets)
    print(f"  tag 数量: {len(out['headers'])}")
    print(f"  数据行数: {len(out['rows'])}")
    print(f"  A1: {out['a1']}")
    print(f"  时间方向: {'倒序 (新→旧)' if out['rows'] and out['rows'][0][0] > out['rows'][-1][0] else '正序 (旧→新)'}")
    if out["rows"]:
        print(f"  首行: {out['rows'][0]}")
        print(f"  末行: {out['rows'][-1]}")

    # 3. 写 xlsx (xlsx_io 负责)
    print(f"\n[3/3] 写 {args.output} ...")
    write_wide_xlsx(args.output, a1=out["a1"], headers=out["headers"], rows=out["rows"])
    print(f"  完成")

    # 4. 可选上传
    if args.upload:
        from common_api import AlgAPI
        api = AlgAPI("http://10.10.58.179:31501")
        api.login("admin", "123456", "")
        print(f"\n[4/4] 上传 {args.output} ...")
        r = api.import_tag_value_history(args.output)
        print(f"  is_success={r['is_success']} code={r['code']} requestId={r['raw'].get('requestId') if r['raw'] else None}")


if __name__ == "__main__":
    main()
