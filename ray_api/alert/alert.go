package alert

import (
	"fmt"
	"sync"

	"raymonitor/config"
	"raymonitor/logx"
	"raymonitor/model"
)

type Store interface {
	CreateAlert(model.Alert) (model.Alert, error)
	FindActiveAlert(clusterID, objectType, objectID, metric string) (*model.Alert, error)
	UpdateAlert(model.Alert) error
	AckAlert(id int64) error
	AddAlertEvent(model.AlertEvent) error
}

type Manager struct {
	store    Store
	recoverN int

	mu       sync.Mutex
	belowCnt map[string]int
}

func NewManager(store Store, recoverConsecutive int) *Manager {
	if recoverConsecutive <= 0 {
		recoverConsecutive = 3
	}
	return &Manager{
		store:    store,
		recoverN: recoverConsecutive,
		belowCnt: map[string]int{},
	}
}

func (m *Manager) Check(clusterID, clusterName string, th config.Thresholds, nodes []model.NodeMetric, workers []model.WorkerSnapshot, staleNodes map[string]bool) {
	nodeByID := map[string]model.NodeMetric{}
	nodeHost := map[string]string{}
	for _, n := range nodes {
		nodeByID[n.NodeID] = n
		nodeHost[n.NodeID] = n.Hostname
		if nodeHost[n.NodeID] == "" {
			nodeHost[n.NodeID] = n.IP
		}
	}

	for _, n := range nodes {
		if staleNodes[n.NodeID] {
			continue
		}
		if n.IsPartial {
			continue
		}
		nodeName := n.Hostname
		if nodeName == "" {
			nodeName = n.IP
		}

		if n.MemTotal > 0 {
			memPct := pct(float64(n.MemUsed), float64(n.MemTotal))
			m.checkMetric(clusterID, clusterName, nodeName, "node", n.NodeID, nodeName, "mem", th.NodeMEM, memPct)
		}

		if n.GPUTotal > 0 {
			gpuPct := pct(n.GPUUsed, n.GPUTotal)
			m.checkMetric(clusterID, clusterName, nodeName, "node", n.NodeID, nodeName, "gpu", th.NodeGPU, gpuPct)
		}

		if n.CPU > 0 {
			m.checkMetric(clusterID, clusterName, nodeName, "node", n.NodeID, nodeName, "cpu", th.NodeCPU, n.CPU)
		}
	}

	for _, w := range workers {
		if staleNodes[w.NodeID] {
			continue
		}

		m.checkMetric(clusterID, clusterName, nodeHost[w.NodeID], "worker", workerObjectID(w), workerName(w), "cpu", th.WorkerCPU, w.CPUPercent)

		if node, ok := nodeByID[w.NodeID]; ok && node.MemTotal > 0 {
			workerMemPct := pct(float64(w.MemRSS), float64(node.MemTotal))
			m.checkMetric(clusterID, clusterName, nodeHost[w.NodeID], "worker", workerObjectID(w), workerName(w), "mem", th.WorkerMEM, workerMemPct)
		}

		if node, ok := nodeByID[w.NodeID]; ok && node.GPUTotal > 0 {
			workerGpuPct := pct(w.GPUUsed, node.GPUTotal)
			m.checkMetric(clusterID, clusterName, nodeHost[w.NodeID], "worker", workerObjectID(w), workerName(w), "gpu", th.WorkerGPU, workerGpuPct)
		}
	}
}

func (m *Manager) checkMetric(clusterID, clusterName, nodeName, objType, objID, objName, metric string, threshold, valuePct float64) {
	if threshold <= 0 {
		return
	}
	key := fmt.Sprintf("%s|%s|%s|%s", clusterID, objType, objID, metric)
	m.mu.Lock()
	cnt := m.belowCnt[key]
	m.mu.Unlock()

	now := model.NowMs()
	existing, err := m.store.FindActiveAlert(clusterID, objType, objID, metric)
	if err != nil {
		logx.L().Warn("alert find failed", "err", err)
		return
	}

	if valuePct >= threshold {
		m.mu.Lock()
		m.belowCnt[key] = 0
		m.mu.Unlock()

		if existing == nil {
			a := model.Alert{
				ClusterID: clusterID, ClusterName: clusterName, NodeName: nodeName,
				ObjectType: objType, ObjectID: objID, ObjectName: objName,
				Metric: metric, Threshold: threshold,
				FirstTriggerTs: now, LastTriggerTs: now, LastValue: valuePct,
			}
			a, err = m.store.CreateAlert(a)
			if err != nil {
				logx.L().Warn("alert create failed", "err", err)
				return
			}
			if err := m.store.AddAlertEvent(model.AlertEvent{Ts: now, AlertID: a.ID, Event: "trigger", Value: valuePct}); err != nil {
				logx.L().Warn("alert event write failed", "err", err)
			}
			logx.L().Info("alert triggered", "cluster", clusterID, "obj", objName, "metric", metric, "value", valuePct)
		} else {
			existing.LastTriggerTs = now
			existing.LastValue = valuePct
			if existing.Recovered {
				existing.Recovered = false
				existing.RecoverTs = 0
			}
			if err := m.store.UpdateAlert(*existing); err != nil {
				logx.L().Warn("alert update failed", "err", err)
			}
			if err := m.store.AddAlertEvent(model.AlertEvent{Ts: now, AlertID: existing.ID, Event: "trigger", Value: valuePct}); err != nil {
				logx.L().Warn("alert event write failed", "err", err)
			}
		}
	} else {
		if existing == nil || existing.Recovered {
			m.mu.Lock()
			m.belowCnt[key] = cnt + 1
			m.mu.Unlock()
			return
		}
		m.mu.Lock()
		m.belowCnt[key] = cnt + 1
		newCnt := m.belowCnt[key]
		m.mu.Unlock()

		if newCnt >= m.recoverN {
			existing.Recovered = true
			existing.RecoverTs = now
			if err := m.store.UpdateAlert(*existing); err != nil {
				logx.L().Warn("alert update failed", "err", err)
			}
			if err := m.store.AddAlertEvent(model.AlertEvent{Ts: now, AlertID: existing.ID, Event: "recover"}); err != nil {
				logx.L().Warn("alert event write failed", "err", err)
			}
			logx.L().Info("alert recovered", "cluster", clusterID, "obj", objName, "metric", metric)
			m.tryEliminate(existing, now)
			m.mu.Lock()
			m.belowCnt[key] = 0
			m.mu.Unlock()
		}
	}
}

func (m *Manager) tryEliminate(a *model.Alert, now int64) {
	if a.Recovered && a.Acknowledged && a.EliminatedTs == 0 {
		a.EliminatedTs = now
		if err := m.store.UpdateAlert(*a); err != nil {
			logx.L().Warn("alert eliminate update failed", "err", err)
		}
		if err := m.store.AddAlertEvent(model.AlertEvent{Ts: now, AlertID: a.ID, Event: "eliminate"}); err != nil {
			logx.L().Warn("alert event write failed", "err", err)
		}
	}
}

func (m *Manager) Ack(alertID int64) error {
	if err := m.store.AckAlert(alertID); err != nil {
		return err
	}
	return nil
}

func (m *Manager) ListActive(clusterID string) ([]model.Alert, error) {
	type lister interface {
		ListActiveAlerts(string) ([]model.Alert, error)
	}
	if l, ok := m.store.(lister); ok {
		return l.ListActiveAlerts(clusterID)
	}
	return nil, fmt.Errorf("store does not support ListActiveAlerts")
}

func (m *Manager) CountActive(clusterID string) (int, error) {
	type counter interface {
		CountActiveAlerts(string) (int, error)
	}
	if c, ok := m.store.(counter); ok {
		return c.CountActiveAlerts(clusterID)
	}
	return 0, fmt.Errorf("store does not support CountActiveAlerts")
}

func workerObjectID(w model.WorkerSnapshot) string {
	return fmt.Sprintf("%s:%d", w.NodeID, w.PID)
}

func workerName(w model.WorkerSnapshot) string {
	name := w.ProcessName
	if name == "" {
		name = "ray::?"
	}
	return fmt.Sprintf("%s (pid %d)", name, w.PID)
}

func pct(used, total float64) float64 {
	if total <= 0 {
		return 0
	}
	return used / total * 100
}
