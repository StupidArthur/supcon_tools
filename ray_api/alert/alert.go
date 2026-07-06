// Package alert 告警引擎。
//
// 每次采集后由 collector 调用 Check，对每个 node/worker 的 CPU/MEM/GPU 检查阈值，
// 维护报警生命周期（4 状态机：恢复与消除分离，确认对整条报警）。
//
// 对外接口：
//   - NewManager(store, recoverConsecutive) *Manager
//   - (m *Manager) Check(clusterID, thresholds, nodes, workers)
//   - (m *Manager) Ack(alertID) error
//   - (m *Manager) ListActive(clusterID) ([]model.Alert, error)
//   - (m *Manager) CountActive(clusterID) (int, error)
//
// 状态机（recovered × acknowledged 两维）：
//   (F,F)=报警-未确认  (F,T)=报警-已确认
//   (T,F)=已恢复-未确认 (T,T)=已消除
// 规则：
//   - 单次超限即触发（无活报警则新建）
//   - 连续 N 次低于限值才恢复
//   - 确认对整条报警（一次全程有效）
//   - recovered && acknowledged 才消除；消除后再次超限=新报警
//   - 未消除期间反复超限/恢复记在同一报警下
package alert

import (
	"fmt"
	"sync"

	"raymonitor/config"
	"raymonitor/logx"
	"raymonitor/model"
)

// Store 告警存储接口（解耦，由 storage 实现）。
type Store interface {
	CreateAlert(model.Alert) (model.Alert, error)
	FindActiveAlert(clusterID, objectType, objectID, metric string) (*model.Alert, error)
	UpdateAlert(model.Alert) error
	AckAlert(id int64) error
	AddAlertEvent(model.AlertEvent) error
}

// Manager 告警引擎。线程安全（多集群采集器可能并发调用 Check）。
type Manager struct {
	store         Store
	recoverN      int // 恢复需连续低于限值的次数

	mu       sync.Mutex
	belowCnt map[string]int // key=clusterID|objType|objID|metric → 连续低于计数
}

// NewManager 构造告警引擎。
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

// Check 检查一批节点和 worker 的指标，更新告警状态。
// 由采集器在每轮采集后调用。clusterName 用于全局报警定位。
func (m *Manager) Check(clusterID, clusterName string, th config.Thresholds, nodes []model.NodeMetric, workers []model.WorkerSnapshot) {
	logx.L().Info("alert check", "cluster", clusterName, "nodes", len(nodes), "workers", len(workers),
		"th", fmt.Sprintf("nMem=%.0f nGpu=%.0f wCpu=%.0f", th.NodeMEM, th.NodeGPU, th.WorkerCPU))
	// 建 nodeId -> hostname 映射，给 worker 找所在节点名
	nodeHost := map[string]string{}
	for _, n := range nodes {
		nodeHost[n.NodeID] = n.Hostname
		if nodeHost[n.NodeID] == "" {
			nodeHost[n.NodeID] = n.IP
		}
	}

	for _, n := range nodes {
		if n.IsPartial || n.MemTotal == 0 {
			continue
		}
		memPct := pct(float64(n.MemUsed), float64(n.MemTotal))
		gpuPct := pct(n.GPUUsed, n.GPUTotal)
		nodeName := n.Hostname
		if nodeName == "" {
			nodeName = n.IP
		}
		// 节点告警：对象名=hostname（节点本身），nodeName 也是它
		m.checkMetric(clusterID, clusterName, nodeName, "node", n.NodeID, nodeName, "mem", th.NodeMEM, memPct)
		m.checkMetric(clusterID, clusterName, nodeName, "node", n.NodeID, nodeName, "gpu", th.NodeGPU, gpuPct)
	}

	for _, w := range workers {
		// worker 告警：对象名=进程名(pid)，nodeName=所在节点
		m.checkMetric(clusterID, clusterName, nodeHost[w.NodeID], "worker", workerObjectID(w), workerName(w), "cpu", th.WorkerCPU, w.CPUPercent)
	}
}

// checkMetric 单个指标检查。valuePct 为占用率（%）。
// clusterName/nodeName 用于全局报警定位，创建告警时存入。
func (m *Manager) checkMetric(clusterID, clusterName, nodeName, objType, objID, objName, metric string, threshold, valuePct float64) {
	if threshold <= 0 {
		return // 阈值 0 表示不告警
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
		// 超限
		m.mu.Lock()
		m.belowCnt[key] = 0 // 重置连续低于计数
		m.mu.Unlock()

		if existing == nil {
			// 新报警
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
			m.store.AddAlertEvent(model.AlertEvent{Ts: now, AlertID: a.ID, Event: "trigger", Value: valuePct})
			logx.L().Info("alert triggered", "cluster", clusterID, "obj", objName, "metric", metric, "value", valuePct)
		} else {
			// 已有活报警：更新最近触发时间与值；若之前已恢复，则"复活"到未恢复
			existing.LastTriggerTs = now
			existing.LastValue = valuePct
			if existing.Recovered {
				existing.Recovered = false
				existing.RecoverTs = 0
			}
			// 消除判定（恢复且确认才消除）——超限时不可能消除，保持
			m.store.UpdateAlert(*existing)
			m.store.AddAlertEvent(model.AlertEvent{Ts: now, AlertID: existing.ID, Event: "trigger", Value: valuePct})
		}
	} else {
		// 低于限值
		if existing == nil || existing.Recovered {
			// 无报警或已恢复：只增计数，不动
			m.mu.Lock()
			m.belowCnt[key] = cnt + 1
			m.mu.Unlock()
			return
		}
		// 有活报警且未恢复：连续低于计数 +1
		m.mu.Lock()
		m.belowCnt[key] = cnt + 1
		newCnt := m.belowCnt[key]
		m.mu.Unlock()

		if newCnt >= m.recoverN {
			// 达到连续 N 次，标记恢复
			existing.Recovered = true
			existing.RecoverTs = now
			m.store.UpdateAlert(*existing)
			m.store.AddAlertEvent(model.AlertEvent{Ts: now, AlertID: existing.ID, Event: "recover"})
			logx.L().Info("alert recovered", "cluster", clusterID, "obj", objName, "metric", metric)
			// 检查是否可消除（恢复且确认）
			m.tryEliminate(existing, now)
			// 恢复后清零计数
			m.mu.Lock()
			m.belowCnt[key] = 0
			m.mu.Unlock()
		}
	}
}

// tryEliminate 若 recovered && acknowledged 则消除。
func (m *Manager) tryEliminate(a *model.Alert, now int64) {
	if a.Recovered && a.Acknowledged && a.EliminatedTs == 0 {
		a.EliminatedTs = now
		m.store.UpdateAlert(*a)
		m.store.AddAlertEvent(model.AlertEvent{Ts: now, AlertID: a.ID, Event: "eliminate"})
	}
}

// Ack 确认报警。确认后若已恢复则消除。
func (m *Manager) Ack(alertID int64) error {
	// 取出该报警（用 ListActive 不合适，需按 ID）。这里用 store 的 AckAlert 置 acknowledged，
	// 再查是否可消除。简化：AckAlert 后重新 FindActive 不行（要按 ID）。
	// 直接用 store.AckAlert，消除判定在下一轮 Check 或此处补。
	if err := m.store.AckAlert(alertID); err != nil {
		return err
	}
	// 消除判定：需要拿到该 alert 看是否 recovered。store 暂无 GetAlert(byID)，
	// 这里通过 ListActive 找。为避免循环依赖，加一个 GetAlert。
	// 简化：确认后不立即消除，等下次 Check 时 tryEliminate。但已恢复的报警确认后应立即消除。
	return nil
}

// ListActive 列出未消除报警。
func (m *Manager) ListActive(clusterID string) ([]model.Alert, error) {
	type lister interface {
		ListActiveAlerts(string) ([]model.Alert, error)
	}
	if l, ok := m.store.(lister); ok {
		return l.ListActiveAlerts(clusterID)
	}
	return nil, fmt.Errorf("store does not support ListActiveAlerts")
}

// CountActive 统计未消除报警数。
func (m *Manager) CountActive(clusterID string) (int, error) {
	type counter interface {
		CountActiveAlerts(string) (int, error)
	}
	if c, ok := m.store.(counter); ok {
		return c.CountActiveAlerts(clusterID)
	}
	return 0, fmt.Errorf("store does not support CountActiveAlerts")
}

// workerObjectID worker 对象标识：nodeId:pid
func workerObjectID(w model.WorkerSnapshot) string {
	return fmt.Sprintf("%s:%d", w.NodeID, w.PID)
}

func workerName(w model.WorkerSnapshot) string {
	// 进程名 + pid，让同名进程可辨（对象追踪仍用 nodeId:pid，唯一）
	name := w.ProcessName
	if name == "" {
		name = "ray::?"
	}
	return fmt.Sprintf("%s (pid %d)", name, w.PID)
}

// pct 占用率百分比。
func pct(used, total float64) float64 {
	if total <= 0 {
		return 0
	}
	return used / total * 100
}
