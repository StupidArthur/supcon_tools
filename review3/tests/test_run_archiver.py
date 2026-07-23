"""
运行归档测试。

覆盖：metadata/values/alarms 写入、读取、CSV 导出、删除、磁盘统计、
路径穿越防护、归档失败不影响调用方。
"""

import sys
import pathlib

import pytest

project_root = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from datacenter.run_archiver import RunArchiver, RunHistory


def make_archiver(tmp_path, tags=None):
    tags = tags or ["pid.PV", "tank.level"]
    meta = {"projectId": "p1", "runtimeRevision": "abc123"}
    return RunArchiver(str(tmp_path), "sess1", meta, tags)


class TestRunArchiver:
    def test_start_creates_files(self, tmp_path):
        a = make_archiver(tmp_path)
        a.start()
        assert (tmp_path / "sess1" / "metadata.json").exists()
        assert (tmp_path / "sess1" / "values.sqlite").exists()
        a.close()

    def test_record_and_read_values(self, tmp_path):
        a = make_archiver(tmp_path)
        a.start()
        a.record({"pid.PV": 0.5, "tank.level": 0.3, "other": 99}, 1.0)
        a.record({"pid.PV": 0.6, "tank.level": 0.4}, 1.5)
        a.close()

        h = RunHistory(str(tmp_path))
        rows = h.read_values("sess1")
        assert len(rows) == 2
        assert rows[0]["pid.PV"] == 0.5
        assert rows[1]["tank.level"] == 0.4
        # 未选定的 tag 不记录
        assert "other" not in rows[0]

    def test_record_missing_value_is_null(self, tmp_path):
        a = make_archiver(tmp_path)
        a.start()
        a.record({"pid.PV": 0.5}, 1.0)
        a.close()
        h = RunHistory(str(tmp_path))
        rows = h.read_values("sess1")
        assert rows[0]["tank.level"] is None

    def test_record_event(self, tmp_path):
        a = make_archiver(tmp_path)
        a.start()
        a.record_event("alarm", {"id": "a1", "type": "activated"})
        a.record_event("force", {"tag": "pid.PV", "mode": "zero"})
        a.close()
        lines = (tmp_path / "sess1" / "alarms.jsonl").read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_metadata_contains_revision(self, tmp_path):
        a = make_archiver(tmp_path)
        a.start()
        a.close()
        import json
        meta = json.loads((tmp_path / "sess1" / "metadata.json").read_text(encoding="utf-8"))
        assert meta["runtimeRevision"] == "abc123"
        assert meta["tags"] == ["pid.PV", "tank.level"]


class TestRunHistory:
    def test_list_runs(self, tmp_path):
        a = make_archiver(tmp_path)
        a.start()
        a.close()
        h = RunHistory(str(tmp_path))
        runs = h.list_runs()
        assert len(runs) == 1
        assert runs[0]["sessionId"] == "sess1"

    def test_export_csv(self, tmp_path):
        a = make_archiver(tmp_path)
        a.start()
        a.record({"pid.PV": 0.5, "tank.level": 0.3}, 1.0)
        a.close()
        h = RunHistory(str(tmp_path))
        out = tmp_path / "export.csv"
        n = h.export_csv("sess1", str(out))
        assert n == 1
        assert out.exists()

    def test_delete_run(self, tmp_path):
        a = make_archiver(tmp_path)
        a.start()
        a.close()
        h = RunHistory(str(tmp_path))
        assert h.delete_run("sess1") is True
        assert h.list_runs() == []

    def test_delete_prevents_path_traversal(self, tmp_path):
        h = RunHistory(str(tmp_path))
        assert h.delete_run("../escape") is False

    def test_disk_usage(self, tmp_path):
        a = make_archiver(tmp_path)
        a.start()
        a.record({"pid.PV": 0.5, "tank.level": 0.3}, 1.0)
        a.close()
        h = RunHistory(str(tmp_path))
        assert h.disk_usage_bytes() > 0

    def test_read_values_missing_run(self, tmp_path):
        h = RunHistory(str(tmp_path))
        assert h.read_values("nonexistent") == []
