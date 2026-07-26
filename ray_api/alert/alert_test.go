package alert

import (
	"sync"
	"testing"

	"raymonitor/model"
)

type memoryAlertStore struct {
	mu     sync.Mutex
	active *model.Alert
}

func (s *memoryAlertStore) CreateAlert(a model.Alert) (model.Alert, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	a.ID = 1
	s.active = &a
	return a, nil
}

func (s *memoryAlertStore) FindActiveAlert(_, _, _, _ string) (*model.Alert, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.active == nil {
		return nil, nil
	}
	copy := *s.active
	return &copy, nil
}

func (s *memoryAlertStore) UpdateAlert(a model.Alert) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.active = &a
	return nil
}

func (s *memoryAlertStore) AckAlert(int64) error                 { return nil }
func (s *memoryAlertStore) AddAlertEvent(model.AlertEvent) error { return nil }

func TestRecoverConsecutiveHotUpdatePreservesBelowCount(t *testing.T) {
	store := &memoryAlertStore{active: &model.Alert{ID: 1}}
	manager := NewManager(store)

	check := func() {
		manager.checkMetric("cluster", "cluster", "node", "worker", "worker", "worker", "cpu", 50, 10)
	}
	check()
	check()
	manager.UpdateRecoverConsecutive(4)
	check()
	if store.active.Recovered {
		t.Fatal("alert recovered after only three consecutive below-threshold checks")
	}
	check()
	if !store.active.Recovered {
		t.Fatal("alert did not preserve the earlier below-threshold count")
	}
}

func TestRecoverConsecutiveHotUpdateUsesLowerValueOnNextCheck(t *testing.T) {
	store := &memoryAlertStore{active: &model.Alert{ID: 1}}
	manager := NewManager(store)

	manager.checkMetric("cluster", "cluster", "node", "worker", "worker", "worker", "cpu", 50, 10)
	manager.checkMetric("cluster", "cluster", "node", "worker", "worker", "worker", "cpu", 50, 10)
	manager.UpdateRecoverConsecutive(2)
	if store.active.Recovered {
		t.Fatal("configuration update must not recover an alert synchronously")
	}
	manager.checkMetric("cluster", "cluster", "node", "worker", "worker", "worker", "cpu", 50, 10)
	if !store.active.Recovered {
		t.Fatal("lower recovery count was not used on the next check")
	}
}
