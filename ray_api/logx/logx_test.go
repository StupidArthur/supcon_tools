package logx

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestEventWritesDimensionFilesAndRotatesByDate(t *testing.T) {
	dir := t.TempDir()
	originalNow := nowFunc
	t.Cleanup(func() {
		Close()
		nowFunc = originalNow
	})

	nowFunc = func() time.Time {
		return time.Date(2026, 7, 26, 23, 59, 0, 0, time.Local)
	}
	if _, err := Init(dir); err != nil {
		t.Fatal(err)
	}
	Event("api", "first", "status", 200)
	nowFunc = func() time.Time {
		return time.Date(2026, 7, 27, 0, 1, 0, 0, time.Local)
	}
	Event("api", "second", "status", 503)
	Close()

	for _, name := range []string{"api_2026-07-26.jsonl", "api_2026-07-27.jsonl"} {
		path := filepath.Join(dir, name)
		file, err := os.Open(path)
		if err != nil {
			t.Fatalf("open %s: %v", name, err)
		}
		scanner := bufio.NewScanner(file)
		if !scanner.Scan() {
			_ = file.Close()
			t.Fatalf("%s is empty", name)
		}
		var event map[string]any
		if err := json.Unmarshal(scanner.Bytes(), &event); err != nil {
			_ = file.Close()
			t.Fatalf("%s is not JSONL: %v", name, err)
		}
		_ = file.Close()
	}
}

func TestEventRejectsArbitraryDimensionPath(t *testing.T) {
	dir := t.TempDir()
	if _, err := Init(dir); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(Close)
	Event("../outside", "safe")
	date := nowFunc().Format("2006-01-02")
	if _, err := os.Stat(filepath.Join(dir, "app_"+date+".jsonl")); err != nil {
		t.Fatalf("unknown dimension did not fall back to app log: %v", err)
	}
}
