"""
smoke test:最基础的 import 和 read/write 一个简单 CSV。
"""
import sys
from pathlib import Path

# 让 supcon_io 可以直接被 import(测试从仓库根跑)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from supcon_io import read, write, Table, parse_time, ExcelPrecisionError


def test_imports():
    assert callable(read)
    assert callable(write)
    assert callable(parse_time)
    assert Table is not None


def test_table_namedtuple():
    t = Table(title=["a", "b"], desc=None, data=[["1", "2"]])
    assert t.title == ["a", "b"]
    assert t.desc is None
    assert t.data == [["1", "2"]]


def test_parse_time_two_promises():
    # 承诺 cover 的 2 种
    assert parse_time("2024/06/30 12:00:00").year == 2024
    assert parse_time("2024-06-30 12:00:00").year == 2024
    # 失败
    assert parse_time("") is None
    assert parse_time("not a time") is None
    assert parse_time(None) is None


def test_csv_roundtrip(tmp_path: Path):
    csv_path = tmp_path / "demo.csv"
    csv_path.write_text(
        "timeStamp,temperature,设备名\n"
        "2024/06/30 12:00:00,25.5,反应釜R101\n"
        "2024/06/30 12:00:01,26.0,反应釜R101\n",
        encoding="utf-8",
    )

    # 显式 sniff=False 走严格参数;encoding 没有 None 走 sniff,因为不传
    table = read(csv_path, sniff=False, encoding="utf-8", delimiter=",")
    assert table.title == ["timeStamp", "temperature", "设备名"]
    assert table.desc is None
    assert len(table.data) == 2
    assert table.data[0][0] == "2024/06/30 12:00:00"
    assert table.data[0][1] == "25.5"
    assert table.data[0][2] == "反应釜R101"

    # round-trip:写回去再读
    out_path = tmp_path / "out.csv"
    write(out_path, table, encoding="utf-8")
    table2 = read(out_path, sniff=False, encoding="utf-8", delimiter=",")
    assert table2.title == table.title
    assert table2.data == table.data


def test_csv_sniff_default(tmp_path: Path):
    """不传 encoding/delimiter,走 sniff。"""
    p = tmp_path / "auto.csv"
    p.write_text(
        "a,b,c\n"
        "1,2,3\n"
        "4,5,6\n",
        encoding="utf-8",
    )
    table = read(p)  # 全走 sniff
    assert table.title == ["a", "b", "c"]
    assert len(table.data) == 2


def test_csv_double_header_sniff(tmp_path: Path):
    """中文描述行 sniffed 为双行表头。"""
    p = tmp_path / "zh.csv"
    p.write_text(
        "timeStamp,温度,压力\n"
        "时间戳,摄氏度,MPa\n"
        "2024/06/30 12:00:00,25.5,0.1\n",
        encoding="utf-8",
    )
    table = read(p)
    assert table.title == ["timeStamp", "温度", "压力"]
    assert table.desc == ["时间戳", "摄氏度", "MPa"]
    assert len(table.data) == 1


def test_csv_gbk_roundtrip(tmp_path: Path):
    p = tmp_path / "gbk.csv"
    p.write_bytes(
        "timeStamp,设备名\n".encode("gbk")
        + "2024/06/30 12:00:00,反应釜R101\n".encode("gbk")
    )
    # 不传 encoding → sniff 命中 gbk
    table = read(p)
    assert table.title == ["timeStamp", "设备名"]
    assert table.data[0][1] == "反应釜R101"


def test_excel_numeric_forbid(tmp_path: Path):
    """xlsx 数字 cell 触发 ExcelPrecisionError。"""
    try:
        from openpyxl import Workbook
    except ImportError:
        return  # 跳过(没装 openpyxl)

    p = tmp_path / "num.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["col_str", "col_num"])
    ws.append(["hello", 25.5])  # 数字 cell
    wb.save(p)

    try:
        read(p, sniff=False)
    except ExcelPrecisionError as e:
        assert "forbid" in str(e)
        return
    assert False, "should have raised ExcelPrecisionError"


def test_xlsx_with_text_only(tmp_path: Path):
    """纯文本 cell 的 xlsx 能 read 通,forbid 模式不挂。"""
    try:
        from openpyxl import Workbook
    except ImportError:
        return

    p = tmp_path / "text.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["timeStamp", "device"])
    ws.append(["2024-06-30 12:00:00", "R101"])
    ws.append(["2024-06-30 12:00:01", "R102"])
    wb.save(p)

    table = read(p, sniff=False)
    assert table.title == ["timeStamp", "device"]
    assert len(table.data) == 2


def test_unsupported_ext(tmp_path: Path):
    p = tmp_path / "weird.txt"
    p.write_text("hello")
    try:
        read(p)
    except ValueError as e:
        assert "不支持的扩展名" in str(e)
        return
    assert False, "should have raised ValueError"


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        # 简单 smoke,非正式 pytest
        for fn_name, fn in list(globals().items()):
            if fn_name.startswith("test_") and callable(fn):
                print(f"  running {fn_name} ...", end=" ")
                try:
                    fn(d)
                    print("OK")
                except Exception as e:
                    print(f"FAIL: {e!r}")
                    raise
        print("all smoke tests passed")
