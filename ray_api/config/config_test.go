package config

import (
	"encoding/json"
	"testing"
)

// 测试 v1 旧配置迁移到简化格式（集群只填 URL，采样间隔提全局）。
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
	// 集群不再有 cookie/间隔字段
	if c.ID == "" {
		t.Errorf("cluster should have ID")
	}
	// 采样间隔迁移到全局
	if cfg.SampleEvery != 15 {
		t.Errorf("sampleEvery should migrate from summaryEvery=15, got %d", cfg.SampleEvery)
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
	// 空 URL 回退到 ID
	cl := ClusterConfig{ID: "abc", PlatformURL: ""}
	if cl.DisplayName() != "abc" {
		t.Errorf("empty url should fallback to id, got %s", cl.DisplayName())
	}
}

// 测试统一采样间隔解析。
func TestSampleInterval(t *testing.T) {
	cfg := Config{SampleEvery: 7}
	if cfg.SampleInterval() != 7 {
		t.Errorf("want 7, got %d", cfg.SampleInterval())
	}
	// 非正兜底 10
	cfg2 := Config{}
	if cfg2.SampleInterval() != 10 {
		t.Errorf("want default 10, got %d", cfg2.SampleInterval())
	}
}

// 测试 v2 简化配置正常解析。
func TestParseV2(t *testing.T) {
	v2 := `{
		"clusters": [
			{"id": "c1", "platformUrl": "http://1.2.3.4:32549"}
		],
		"dbPath": "x.db",
		"sampleEvery": 10,
		"thresholds": {"nodeCpu": 90, "nodeMem": 85, "nodeGpu": 95, "workerCpu": 70, "workerMem": 70, "workerGpu": 90}
	}`
	var parsed Config
	if err := json.Unmarshal([]byte(v2), &parsed); err != nil {
		t.Fatalf("parse v2: %v", err)
	}
	if len(parsed.Clusters) != 1 || parsed.Clusters[0].PlatformURL != "http://1.2.3.4:32549" {
		t.Errorf("v2 clusters not parsed: %+v", parsed.Clusters)
	}
	if parsed.SampleEvery != 10 {
		t.Errorf("sampleEvery not parsed: %d", parsed.SampleEvery)
	}
	if parsed.Thresholds.NodeCPU != 90 {
		t.Errorf("thresholds not parsed: %+v", parsed.Thresholds)
	}
}
