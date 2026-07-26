package collector

import (
	"sync"
	"testing"

	"raymonitor/config"
	"raymonitor/model"
)

type recordingChecker struct {
	mu         sync.Mutex
	thresholds []config.Thresholds
}

func (c *recordingChecker) Check(_ string, _ string, th config.Thresholds, _ []model.NodeMetric, _ []model.WorkerSnapshot, _ map[string]bool) {
	c.mu.Lock()
	c.thresholds = append(c.thresholds, th)
	c.mu.Unlock()
}

func (c *recordingChecker) last() config.Thresholds {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.thresholds[len(c.thresholds)-1]
}

func managerConfig() config.Config {
	cfg := config.Default()
	cfg.Clusters = []config.ClusterConfig{{ID: "cluster", PlatformURL: "http://ray"}}
	cfg.Thresholds.WorkerCPU = 80
	return cfg
}

func TestThresholdOnlyConfigChangeUsesNewThresholds(t *testing.T) {
	cfg := managerConfig()
	manager := NewManager(&fakeStore{}, cfg)
	checker := &recordingChecker{}
	manager.SetAlertChecker(checker)

	before := manager.entry("cluster").coll
	manager.dispatchAlert("cluster", nil, nil, nil)
	if got := checker.last().WorkerCPU; got != 80 {
		t.Fatalf("initial WorkerCPU threshold = %v, want 80", got)
	}

	cfg.Thresholds.WorkerCPU = 50
	manager.ApplyConfig(cfg)
	after := manager.entry("cluster").coll
	if before != after {
		t.Fatal("threshold-only update rebuilt the collector")
	}
	manager.dispatchAlert("cluster", nil, nil, nil)
	if got := checker.last().WorkerCPU; got != 50 {
		t.Fatalf("updated WorkerCPU threshold = %v, want 50", got)
	}
}

func TestSetAlertCheckerConcurrentWithCollection(t *testing.T) {
	manager := NewManager(&fakeStore{}, managerConfig())
	start := make(chan struct{})
	var wg sync.WaitGroup
	for i := 0; i < 3; i++ {
		wg.Add(1)
		go func(kind int) {
			defer wg.Done()
			<-start
			for n := 0; n < 1000; n++ {
				switch kind {
				case 0:
					manager.SetAlertChecker(&recordingChecker{})
				case 1:
					manager.dispatchAlert("cluster", nil, nil, map[string]bool{})
				case 2:
					_ = manager.Snapshot("cluster")
				}
			}
		}(i)
	}
	close(start)
	wg.Wait()
}
