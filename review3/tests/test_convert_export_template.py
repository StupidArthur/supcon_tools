"""
标准 CSV/XLSX 导出模板转换测试。

验证 _rows_to_export_snapshots / _write_rows_export 按 prediction 模板生成：
- 两行表头（timeStamp / 时间戳 + 某工业数据）
- 仅导出 need_sample=true 的行
- 时间列使用 datetime.fromtimestamp
- 保留原始工程值
"""

import csv
import math
import pathlib
import sys
from datetime import datetime

import pytest

project_root = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from standalone_main import _rows_to_export_snapshots, _write_rows_export


def _sample_rows():
    return [
        {
            "_cycle": 0,
            "_sim_time": 1000.0,
            "_need_sample": False,
            "pid2.MV": 0.0,
            "pid2.PV": 0.1,
            "pid2.SV": 0.8,
        },
        {
            "_cycle": 1,
            "_sim_time": 1000.5,
            "_need_sample": True,
            "pid2.MV": 100.0,
            "pid2.PV": 0.102,
            "pid2.SV": 0.8,
        },
        {
            "_cycle": 2,
            "_sim_time": 1001.0,
            "_need_sample": True,
            "pid2.MV": 98.0,
            "pid2.PV": 0.105,
            "pid2.SV": 0.8,
        },
    ]


def _sample_columns():
    return ["pid2.MV", "pid2.PV", "pid2.SV"]


class TestCSVExport:
    def test_csv_format(self, tmp_path):
        output_path = tmp_path / "result.csv"
        _write_rows_export(
            _sample_rows(),
            _sample_columns(),
            output_path,
            "csv",
            "",
            template_name="prediction",
        )

        with open(output_path, "r", encoding="utf-8-sig", newline="") as f:
            table = list(csv.reader(f))

        assert table[0] == ["timeStamp", "pid2.MV", "pid2.PV", "pid2.SV"]
        assert table[1] == ["时间戳", "某工业数据", "某工业数据", "某工业数据"]
        assert len(table) == 4

        expected_1 = datetime.fromtimestamp(1000.5).strftime("%Y-%m-%d %H:%M:%S")
        expected_2 = datetime.fromtimestamp(1001.0).strftime("%Y-%m-%d %H:%M:%S")
        assert table[2][0] == expected_1
        assert table[3][0] == expected_2

        assert float(table[2][1]) == 100.0
        assert float(table[2][2]) == 0.102
        assert float(table[2][3]) == 0.8

        raw_text = output_path.read_text(encoding="utf-8")
        assert "_cycle" not in raw_text
        assert "_sim_time" not in raw_text
        assert "_need_sample" not in raw_text


class TestXLSXExport:
    def test_xlsx_format(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        output_path = tmp_path / "result.xlsx"
        _write_rows_export(
            _sample_rows(),
            _sample_columns(),
            output_path,
            "xlsx",
            "控制器",
            template_name="prediction",
        )

        wb = openpyxl.load_workbook(output_path)
        ws = wb.active
        assert ws.title == "控制器"

        assert ws["A1"].value == "timeStamp"
        assert ws["A2"].value == "时间戳"
        assert ws["B1"].value == "pid2.MV"
        assert ws["B2"].value == "某工业数据"
        assert ws["C1"].value == "pid2.PV"
        assert ws["C2"].value == "某工业数据"
        assert ws["D1"].value == "pid2.SV"
        assert ws["D2"].value == "某工业数据"

        expected_1 = datetime.fromtimestamp(1000.5).strftime("%Y-%m-%d %H:%M:%S")
        assert ws["A3"].value == expected_1
        assert ws["B3"].value == 100.0
        assert ws["C3"].value == 0.102
        assert ws["D3"].value == 0.8

        assert isinstance(ws["B3"].value, (int, float))
        assert isinstance(ws["C3"].value, (int, float))

        assert ws.max_row == 4


class TestInternalColumnFiltering:
    def test_internal_columns_filtered(self, tmp_path):
        columns = ["_cycle", "pid2.PV", "_sim_time", "pid2.SV", "_need_sample", "pid2.PV"]
        output_path = tmp_path / "result.csv"
        _write_rows_export(
            _sample_rows(),
            columns,
            output_path,
            "csv",
            "",
            template_name="prediction",
        )

        with open(output_path, "r", encoding="utf-8-sig", newline="") as f:
            table = list(csv.reader(f))

        assert table[0] == ["timeStamp", "pid2.PV", "pid2.SV"]


class TestMissingSimTime:
    def test_missing_sim_time_raises(self):
        rows = [{"_cycle": 0, "_need_sample": True, "pid2.PV": 0.8}]
        with pytest.raises(ValueError, match="缺少有效 _sim_time"):
            _rows_to_export_snapshots(rows, ["pid2.PV"])

    def test_nan_sim_time_raises(self):
        rows = [{"_cycle": 0, "_sim_time": float("nan"), "_need_sample": True, "pid2.PV": 0.8}]
        with pytest.raises(ValueError, match="_sim_time"):
            _rows_to_export_snapshots(rows, ["pid2.PV"])

    def test_inf_sim_time_raises(self):
        rows = [{"_cycle": 0, "_sim_time": float("inf"), "_need_sample": True, "pid2.PV": 0.8}]
        with pytest.raises(ValueError, match="_sim_time"):
            _rows_to_export_snapshots(rows, ["pid2.PV"])


class TestMissingNeedSample:
    def test_missing_need_sample_raises(self):
        rows = [{"_cycle": 0, "_sim_time": 1000.0, "pid2.PV": 0.8}]
        with pytest.raises(ValueError, match="缺少有效 _need_sample"):
            _rows_to_export_snapshots(rows, ["pid2.PV"])


class TestNoSampledRows:
    def test_all_false_raises(self):
        rows = [
            {"_cycle": 0, "_sim_time": 1000.0, "_need_sample": False, "pid2.PV": 0.8},
            {"_cycle": 1, "_sim_time": 1001.0, "_need_sample": False, "pid2.PV": 0.9},
        ]
        with pytest.raises(ValueError, match="当前结果没有可导出的采样数据"):
            _rows_to_export_snapshots(rows, ["pid2.PV"])


class TestOriginalValuesNotScaled:
    def test_raw_values_preserved(self, tmp_path):
        rows = [
            {"_cycle": 0, "_sim_time": 1000.0, "_need_sample": True, "pid2.PV": 0.8},
        ]
        output_path = tmp_path / "result.csv"
        _write_rows_export(rows, ["pid2.PV"], output_path, "csv", "", template_name="prediction")

        with open(output_path, "r", encoding="utf-8-sig", newline="") as f:
            table = list(csv.reader(f))

        assert float(table[2][1]) == 0.8


class TestTemplateNameUsed:
    def test_invalid_template_raises(self, tmp_path):
        output_path = tmp_path / "result.csv"
        with pytest.raises(Exception):
            _write_rows_export(
                _sample_rows(),
                _sample_columns(),
                output_path,
                "csv",
                "",
                template_name="nonexistent_template_xyz",
            )
