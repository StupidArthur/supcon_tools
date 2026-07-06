package storage

import (
	"path/filepath"
	"testing"

	"raymonitor/model"
)

// 验证 ListActiveAlerts 能正确 Scan（含 bool 字段 recovered/acknowledged）。
// 排查：CountActiveAlerts 有数但 ListActiveAlerts 返回空，怀疑 Scan bool 报错。
func TestAlertScan(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(filepath.Join(dir, "test.db"))
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	t.Cleanup(func() { s.Close() })

	// 插一条 alert
	a := model.Alert{
		ClusterID: "c1", ClusterName: "host:port", NodeName: "n1",
		ObjectType: "node", ObjectID: "n1", ObjectName: "n1",
		Metric: "mem", Threshold: 80,
		FirstTriggerTs: 100, LastTriggerTs: 100, LastValue: 90,
	}
	a, err = s.CreateAlert(a)
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	// Count
	n, err := s.CountActiveAlerts("")
	if err != nil {
		t.Fatalf("count err: %v", err)
	}
	if n != 1 {
		t.Fatalf("count want 1, got %d", n)
	}

	// List —— 关键：看 Scan 是否报错
	list, err := s.ListActiveAlerts("")
	if err != nil {
		t.Fatalf("list err: %v  ← 这就是报警不显示的根因", err)
	}
	if len(list) != 1 {
		t.Fatalf("list want 1, got %d", len(list))
	}
	if list[0].ClusterName != "host:port" {
		t.Errorf("clusterName wrong: %s", list[0].ClusterName)
	}

	// FindActiveAlert 也测
	got, err := s.FindActiveAlert("c1", "node", "n1", "mem")
	if err != nil {
		t.Fatalf("find err: %v", err)
	}
	if got == nil {
		t.Fatalf("find want non-nil")
	}
}
