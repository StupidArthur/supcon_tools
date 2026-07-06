package config

import (
	"encoding/json"
	"os"
	"testing"
)

// 强制覆盖 $HOME 为 t.TempDir()，让测试不污染真实配置。
func setupTestHome(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	oldHome := os.Getenv("HOME")
	oldUserProfile := os.Getenv("USERPROFILE")
	t.Setenv("HOME", dir)
	t.Setenv("USERPROFILE", dir)
	t.Cleanup(func() {
		os.Setenv("HOME", oldHome)
		os.Setenv("USERPROFILE", oldUserProfile)
	})
	return dir
}

func TestLoad_NotExist(t *testing.T) {
	setupTestHome(t)
	c, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.URL != "" || c.TenantID != "" {
		t.Errorf("expected empty config, got %+v", c)
	}
}

func TestSaveAndLoad(t *testing.T) {
	setupTestHome(t)
	want := &Config{URL: "https://example.com", TenantID: "TENANT1"}
	if err := Save(want); err != nil {
		t.Fatalf("Save: %v", err)
	}

	got, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if got.URL != want.URL || got.TenantID != want.TenantID {
		t.Errorf("got %+v, want %+v", got, want)
	}
}

func TestClear(t *testing.T) {
	setupTestHome(t)
	_ = Save(&Config{URL: "https://example.com"})
	if err := Clear(); err != nil {
		t.Fatalf("Clear: %v", err)
	}
	c, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.URL != "" {
		t.Errorf("expected empty after clear, got URL=%q", c.URL)
	}
	// 再 Clear 也不应报错
	if err := Clear(); err != nil {
		t.Errorf("Clear again: %v", err)
	}
}

func TestSave_NilConfig(t *testing.T) {
	setupTestHome(t)
	if err := Save(nil); err == nil {
		t.Errorf("Save(nil) should return error")
	}
}

// 验证 JSON 字段名是否正确
func TestConfig_JSONTags(t *testing.T) {
	c := Config{URL: "u", TenantID: "t"}
	b, _ := json.Marshal(c)
	want := `{"url":"u","tenantId":"t"}`
	if string(b) != want {
		t.Errorf("json = %s, want %s", string(b), want)
	}
}
