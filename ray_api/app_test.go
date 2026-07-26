package main

import (
	"path/filepath"
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
		alerts:  alert.NewManager(store, cfg.RecoverConsecutive),
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
