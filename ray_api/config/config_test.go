package config

import (
	"encoding/json"
	"testing"
)

// 测试 v1 旧配置迁移到简化格式（集群只填 URL，sampleEvery 保留）。
func TestMigrateFromLegacy(t *testing.T) {
	legacy := `{
		"platformUrl": "http://10.30.144.41:32549",
		"dbPath": "ray_monitor.db",
		"logDir": "logs",
		"summaryEvery": 15,
		"detailEvery": 60,
		"timeoutSec": 8,
		"cookie": "abc",
		"sortBy": "cpu",
		"concurrency": 10
	}`
	cfg := migrateFromLegacy([]byte(legacy))
	if len(cfg.Clusters) != 1 {
		t.Fatalf("want 1 cluster after migration, got %d", len(cfg.Clusters))
	}
	c := cfg.Clusters[0]
	if c.PlatformURL != "http://10.30.144.41:32549" {
		t.Errorf("platformUrl not migrated: %s", c.PlatformURL)
	}
	if c.ID == "" {
		t.Errorf("cluster should have ID")
	}
	if cfg.DBPath != "ray_monitor.db" {
		t.Errorf("dbPath lost: %s", cfg.DBPath)
	}
	if cfg.Thresholds.NodeCPU != 80 {
		t.Errorf("thresholds not defaulted: %+v", cfg.Thresholds)
	}
}

// 测试集群显示名（URL 的 host:port）。
func TestClusterDisplayName(t *testing.T) {
	cases := []struct {
		url  string
		want string
	}{
		{"http://10.30.144.41:32549", "10.30.144.41:32549"},
		{"https://example.com:443/path", "example.com:443/path"},
		{"http://1.2.3.4:80", "1.2.3.4:80"},
	}
	for _, c := range cases {
		cl := ClusterConfig{ID: "x", PlatformURL: c.url}
		if got := cl.DisplayName(); got != c.want {
			t.Errorf("DisplayName(%q) = %q, want %q", c.url, got, c.want)
		}
	}
	cl := ClusterConfig{ID: "abc", PlatformURL: ""}
	if cl.DisplayName() != "abc" {
		t.Errorf("empty url should fallback to id, got %s", cl.DisplayName())
	}
}

// 测试 v2 简化配置正常解析。
func TestParseV2(t *testing.T) {
	v2 := `{
		"clusters": [
			{"id": "c1", "platformUrl": "http://1.2.3.4:32549"}
		],
		"dbPath": "x.db",
		"thresholds": {"nodeCpu": 90, "nodeMem": 85, "nodeGpu": 95, "workerCpu": 70, "workerMem": 70, "workerGpu": 90}
	}`
	var parsed Config
	if err := json.Unmarshal([]byte(v2), &parsed); err != nil {
		t.Fatalf("parse v2: %v", err)
	}
	if len(parsed.Clusters) != 1 || parsed.Clusters[0].PlatformURL != "http://1.2.3.4:32549" {
		t.Errorf("v2 clusters not parsed: %+v", parsed.Clusters)
	}
	if parsed.Thresholds.NodeCPU != 90 {
		t.Errorf("thresholds not parsed: %+v", parsed.Thresholds)
	}
}
