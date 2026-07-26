package main

import (
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"raymonitor/alert"
	"raymonitor/collector"
	"raymonitor/config"
	"raymonitor/storage"
)

func TestAlertManagerAccessConcurrentWithConfigUpdate(t *testing.T) {
	store, err := storage.Open(filepath.Join(t.TempDir(), "app.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })

	cfg := config.Default()
	cfg.Clusters = nil
	app := &App{
		cfg:     cfg,
		store:   store,
		manager: collector.NewManager(store, cfg),
		alerts:  alert.NewManager(store),
	}
	app.manager.SetAlertChecker(app.alerts)

	start := make(chan struct{})
	var wg sync.WaitGroup
	for i := 0; i < 5; i++ {
		wg.Add(1)
		go func(kind int) {
			defer wg.Done()
			<-start
			for n := 0; n < 300; n++ {
				switch kind {
				case 0:
					_ = app.ListAlerts("")
				case 1:
					_ = app.CountAlerts("")
				case 2:
					_ = app.AckAlert(int64(n + 1))
				case 3:
					app.alertManager().UpdateRecoverConsecutive(n%5 + 1)
				case 4:
					next := cfg
					next.Thresholds.WorkerCPU = float64(n%100 + 1)
					app.manager.ApplyConfig(next)
				}
			}
		}(i)
	}
	close(start)
	wg.Wait()
}

func TestExportSnapshot(t *testing.T) {
	app := &App{}
	headers := []string{"节点名", "CPU", "状态"}
	rows := [][]string{
		{"node-1", "12.5", "ALIVE"},
		{"node-2", "80.0", "ALIVE"},
		{"node-3", "0", "DEAD"},
	}

	// 集群名含 Windows 非法字符 ':'，应被替换为 '_'
	res := app.ExportSnapshot("10.30.144.41:32549_节点", headers, rows)
	if !res.Success {
		t.Fatalf("export failed: %s", res.Error)
	}

	// 落在 exe 同级 snapshot/ 目录
	exeDir := filepath.Dir(mustExe(t))
	if !strings.HasPrefix(res.Path, filepath.Join(exeDir, "snapshot")) {
		t.Fatalf("path %s not under snapshot dir", res.Path)
	}
	t.Cleanup(func() { _ = os.RemoveAll(filepath.Join(exeDir, "snapshot")) })

	// 文件名不含 ':' 且含 _snapshot.csv
	base := filepath.Base(res.Path)
	if strings.Contains(base, ":") {
		t.Fatalf("filename contains illegal colon: %s", base)
	}
	if !strings.HasSuffix(base, "_snapshot.csv") {
		t.Fatalf("filename suffix wrong: %s", base)
	}
	if !strings.HasPrefix(base, "10.30.144.41_32549_节点_") {
		t.Fatalf("filename prefix wrong: %s", base)
	}

	// 内容：BOM + 表头 + 3 行
	data, err := os.ReadFile(res.Path)
	if err != nil {
		t.Fatal(err)
	}
	if len(data) < 3 || data[0] != 0xEF || data[1] != 0xBB || data[2] != 0xBF {
		t.Fatalf("missing UTF-8 BOM")
	}
	body := strings.TrimPrefix(string(data), "\ufeff")
	if !strings.Contains(body, "节点名,CPU,状态") {
		t.Fatalf("header row missing: %s", body)
	}
	if !strings.Contains(body, "node-2,80.0,ALIVE") {
		t.Fatalf("data row missing: %s", body)
	}
	if strings.Count(body, "\n") < 4 {
		t.Fatalf("expected >=4 lines, got body:\n%s", body)
	}
}

func mustExe(t *testing.T) string {
	t.Helper()
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	return exe
}
