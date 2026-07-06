// Package storage 实现 SQLite 持久化。
//
// v2：所有表含 cluster_id，支持多集群共库。
// 对外接口：
//   - Open(path) (*Store, error)
//   - (s *Store) Close() error
//   - (s *Store) WriteXxx(clusterID, ...) error
//   - (s *Store) QueryXxx(clusterID, ...) (...)
//
// 遵循 runtime-safety：每批采集立即事务写入；Close 用 defer 刷盘。
// 驱动 modernc.org/sqlite（纯 Go，免 CGO）。
package storage

import (
	"database/sql"
	"fmt"

	_ "modernc.org/sqlite" // 纯 Go SQLite 驱动，注册为 "sqlite"

	"raymonitor/model"
)

// Store SQLite 存储封装。
type Store struct {
	db *sql.DB
}

// Open 打开/创建数据库并建表。path 为 SQLite 文件路径。
func Open(path string) (*Store, error) {
	db, err := sql.Open("sqlite", path+"?_pragma=busy_timeout(5000)&_pragma=journal_mode(WAL)&_txlock=immediate")
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1) // 单写连接，避免 SQLite 多写连接竞争
	if err := db.Ping(); err != nil {
		return nil, err
	}
	s := &Store{db: db}
	if err := s.createSchema(); err != nil {
		return nil, err
	}
	return s, nil
}

// Close 关闭数据库。由调用方 defer 调用确保刷盘。
func (s *Store) Close() error { return s.db.Close() }

// migrateClusterID 为旧表补充 cluster_id 列（v1→v2 迁移）。
// 用 PRAGMA table_info 检测列是否存在，缺失才 ADD COLUMN。
func (s *Store) migrateClusterID() error {
	for _, table := range tablesNeedingClusterID {
		has, err := s.hasColumn(table, "cluster_id")
		if err != nil {
			return err
		}
		if !has {
			if _, err := s.db.Exec(fmt.Sprintf(migrateAddClusterID, table)); err != nil {
				return fmt.Errorf("migrate %s: %w", table, err)
			}
		}
	}
	return nil
}

// hasColumn 检测表是否有指定列。
func (s *Store) hasColumn(table, col string) (bool, error) {
	rows, err := s.db.Query(fmt.Sprintf("PRAGMA table_info(%s)", table))
	if err != nil {
		return false, err
	}
	defer rows.Close()
	for rows.Next() {
		var cid int
		var name, ctype string
		var notnull, pk int
		var dflt sql.NullString
		if err := rows.Scan(&cid, &name, &ctype, &notnull, &dflt, &pk); err != nil {
			return false, err
		}
		if name == col {
			return true, nil
		}
	}
	return false, rows.Err()
}

// ---- 写入方法（每批一事务，带 clusterID）----

// WriteNodeMetrics 写入节点硬件时序。
func (s *Store) WriteNodeMetrics(clusterID string, ns []model.NodeMetric) error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	stmt, err := tx.Prepare(`INSERT INTO node_metric
		(ts,cluster_id,node_id,hostname,ip,is_head,state,cpu,mem_total,mem_used,gpu_total,gpu_used,is_partial)
		VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`)
	if err != nil {
		return err
	}
	defer stmt.Close()
	for _, n := range ns {
		if _, err := stmt.Exec(n.Ts, clusterID, n.NodeID, n.Hostname, n.IP, n.IsHead, n.State,
			n.CPU, n.MemTotal, n.MemUsed, n.GPUTotal, n.GPUUsed, n.IsPartial); err != nil {
			return err
		}
	}
	return tx.Commit()
}

// WriteWorkers 写入 worker 进程快照。
func (s *Store) WriteWorkers(clusterID string, ws []model.WorkerSnapshot) error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	stmt, err := tx.Prepare(`INSERT INTO worker_snapshot
		(ts,cluster_id,node_id,pid,job_id,process_name,cpu_percent,mem_rss,num_fds,language,gpu_used)
		VALUES(?,?,?,?,?,?,?,?,?,?,?)`)
	if err != nil {
		return err
	}
	defer stmt.Close()
	for _, w := range ws {
		if _, err := stmt.Exec(w.Ts, clusterID, w.NodeID, w.PID, w.JobID, w.ProcessName, w.CPUPercent, w.MemRSS, w.NumFds, w.Language, w.GPUUsed); err != nil {
			return err
		}
	}
	return tx.Commit()
}

// WriteActors 写入 Actor 快照。
func (s *Store) WriteActors(clusterID string, as []model.ActorSnapshot) error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	stmt, err := tx.Prepare(`INSERT INTO actor_snapshot
		(ts,cluster_id,node_id,actor_id,actor_class,name,state,num_restarts,job_id,pid,ip_address,num_exec_tasks,gpu_used,exit_detail)
		VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`)
	if err != nil {
		return err
	}
	defer stmt.Close()
	for _, a := range as {
		if _, err := stmt.Exec(a.Ts, clusterID, a.NodeID, a.ActorID, a.ActorClass, a.Name, a.State, a.NumRestarts,
			a.JobID, a.PID, a.IPAddress, a.NumExecTasks, a.GPUUsed, a.ExitDetail); err != nil {
			return err
		}
	}
	return tx.Commit()
}

// WriteJobs 写入作业快照。
func (s *Store) WriteJobs(clusterID string, js []model.JobSnapshot) error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	stmt, err := tx.Prepare(`INSERT INTO job_snapshot
		(ts,cluster_id,job_id,status,start_time,end_time,error_type,entry)
		VALUES(?,?,?,?,?,?,?,?)`)
	if err != nil {
		return err
	}
	defer stmt.Close()
	for _, j := range js {
		if _, err := stmt.Exec(j.Ts, clusterID, j.JobID, j.Status, j.StartTime, j.EndTime, j.ErrorType, j.Entry); err != nil {
			return err
		}
	}
	return tx.Commit()
}

// WriteCluster 写入集群资源时序。
func (s *Store) WriteCluster(clusterID string, c model.ClusterMetric) error {
	_, err := s.db.Exec(`INSERT INTO cluster_metric
		(ts,cluster_id,cpu_total,cpu_used,mem_total,mem_used,gpu_total,gpu_used,heartbeat_max)
		VALUES(?,?,?,?,?,?,?,?,?)`,
		c.Ts, clusterID, c.CPUTotal, c.CPUUsed, c.MemTotal, c.MemUsed, c.GPUTotal, c.GPUUsed, c.HeartbeatMax)
	return err
}

// WriteActorEvents 写入 Actor 状态变迁事件。
func (s *Store) WriteActorEvents(clusterID string, es []model.ActorEvent) error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	stmt, err := tx.Prepare(`INSERT INTO actor_event(ts,cluster_id,actor_id,actor_class,prev_state,new_state,death_cause)
		VALUES(?,?,?,?,?,?,?)`)
	if err != nil {
		return err
	}
	defer stmt.Close()
	for _, e := range es {
		if _, err := stmt.Exec(e.Ts, clusterID, e.ActorID, e.ActorClass, e.PrevState, e.NewState, e.DeathCause); err != nil {
			return err
		}
	}
	return tx.Commit()
}

// WriteJobEvents 写入 Job 状态变迁事件。
func (s *Store) WriteJobEvents(clusterID string, es []model.JobEvent) error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	stmt, err := tx.Prepare(`INSERT INTO job_event(ts,cluster_id,job_id,prev_status,new_status,error_type) VALUES(?,?,?,?,?,?)`)
	if err != nil {
		return err
	}
	defer stmt.Close()
	for _, e := range es {
		if _, err := stmt.Exec(e.Ts, clusterID, e.JobID, e.PrevStatus, e.NewStatus, e.ErrorType); err != nil {
			return err
		}
	}
	return tx.Commit()
}

// ---- 查询方法（带 clusterID 过滤）----

// QueryNodeHistory 查询某集群某节点硬件时序历史。
func (s *Store) QueryNodeHistory(clusterID, nodeID string, from, to int64) ([]model.NodeMetric, error) {
	rows, err := s.db.Query(`SELECT ts,node_id,hostname,ip,is_head,state,cpu,mem_total,mem_used,gpu_total,gpu_used,is_partial
		FROM node_metric WHERE cluster_id=? AND node_id=? AND ts BETWEEN ? AND ? ORDER BY ts`,
		clusterID, nodeID, from, to)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.NodeMetric
	for rows.Next() {
		var n model.NodeMetric
		if err := rows.Scan(&n.Ts, &n.NodeID, &n.Hostname, &n.IP, &n.IsHead, &n.State,
			&n.CPU, &n.MemTotal, &n.MemUsed, &n.GPUTotal, &n.GPUUsed, &n.IsPartial); err != nil {
			return nil, err
		}
		out = append(out, n)
	}
	return out, rows.Err()
}

// QueryActorEvents 查询某集群时间范围内的 Actor 事件。
func (s *Store) QueryActorEvents(clusterID string, from, to int64) ([]model.ActorEvent, error) {
	rows, err := s.db.Query(`SELECT ts,actor_id,actor_class,prev_state,new_state,death_cause
		FROM actor_event WHERE cluster_id=? AND ts BETWEEN ? AND ? ORDER BY ts DESC`, clusterID, from, to)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.ActorEvent
	for rows.Next() {
		var e model.ActorEvent
		if err := rows.Scan(&e.Ts, &e.ActorID, &e.ActorClass, &e.PrevState, &e.NewState, &e.DeathCause); err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

// QueryJobHistory 查询某集群作业历史。status 为空则不限。
func (s *Store) QueryJobHistory(clusterID string, from, to int64, status string) ([]model.JobSnapshot, error) {
	q := `SELECT ts,job_id,status,start_time,end_time,error_type,entry
		FROM job_snapshot WHERE cluster_id=? AND ts BETWEEN ? AND ?`
	args := []interface{}{clusterID, from, to}
	if status != "" {
		q += ` AND status=?`
		args = append(args, status)
	}
	q += ` ORDER BY ts DESC`
	rows, err := s.db.Query(q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.JobSnapshot
	for rows.Next() {
		var j model.JobSnapshot
		if err := rows.Scan(&j.Ts, &j.JobID, &j.Status, &j.StartTime, &j.EndTime, &j.ErrorType, &j.Entry); err != nil {
			return nil, err
		}
		out = append(out, j)
	}
	return out, rows.Err()
}

// ---- 告警存储 ----

// CreateAlert 新建一条报警，返回带 ID 的 alert。
func (s *Store) CreateAlert(a model.Alert) (model.Alert, error) {
	res, err := s.db.Exec(`INSERT INTO alert
		(cluster_id,cluster_name,node_name,object_type,object_id,object_name,metric,threshold,
		 recovered,acknowledged,first_trigger_ts,last_trigger_ts,recover_ts,ack_ts,eliminated_ts,last_value)
		VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
		a.ClusterID, a.ClusterName, a.NodeName, a.ObjectType, a.ObjectID, a.ObjectName, a.Metric, a.Threshold,
		0, 0, a.FirstTriggerTs, a.LastTriggerTs, 0, 0, 0, a.LastValue)
	if err != nil {
		return a, err
	}
	id, _ := res.LastInsertId()
	a.ID = id
	return a, nil
}

// FindActiveAlert 查找某集群某对象某指标未消除的报警。没有返回 nil。
func (s *Store) FindActiveAlert(clusterID, objectType, objectID, metric string) (*model.Alert, error) {
	row := s.db.QueryRow(`SELECT id,cluster_id,cluster_name,node_name,object_type,object_id,object_name,metric,threshold,
		recovered,acknowledged,first_trigger_ts,last_trigger_ts,recover_ts,ack_ts,eliminated_ts,last_value
		FROM alert WHERE cluster_id=? AND object_type=? AND object_id=? AND metric=? AND eliminated_ts=0`,
		clusterID, objectType, objectID, metric)
	var a model.Alert
	err := row.Scan(&a.ID, &a.ClusterID, &a.ClusterName, &a.NodeName, &a.ObjectType, &a.ObjectID, &a.ObjectName, &a.Metric, &a.Threshold,
		&a.Recovered, &a.Acknowledged, &a.FirstTriggerTs, &a.LastTriggerTs, &a.RecoverTs, &a.AckTs, &a.EliminatedTs, &a.LastValue)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &a, nil
}

// UpdateAlert 更新报警状态字段。
func (s *Store) UpdateAlert(a model.Alert) error {
	_, err := s.db.Exec(`UPDATE alert SET recovered=?, acknowledged=?, last_trigger_ts=?, recover_ts=?, ack_ts=?, eliminated_ts=?, last_value=?
		WHERE id=?`, a.Recovered, a.Acknowledged, a.LastTriggerTs, a.RecoverTs, a.AckTs, a.EliminatedTs, a.LastValue, a.ID)
	return err
}

// AckAlert 确认报警。若该报警已恢复，则同时消除（recovered && acknowledged → eliminated）。
func (s *Store) AckAlert(id int64) error {
	now := model.NowMs()
	// 置 acknowledged；若已 recovered 则一并置 eliminated_ts
	_, err := s.db.Exec(`UPDATE alert SET acknowledged=1, ack_ts=?,
		eliminated_ts=CASE WHEN recovered=1 AND eliminated_ts=0 THEN ? ELSE eliminated_ts END
		WHERE id=? AND eliminated_ts=0`, now, now, id)
	if err != nil {
		return err
	}
	// 记消除事件（若刚消除）
	var elim int64
	s.db.QueryRow(`SELECT eliminated_ts FROM alert WHERE id=?`, id).Scan(&elim)
	if elim != 0 {
		s.AddAlertEvent(model.AlertEvent{Ts: now, AlertID: id, Event: "eliminate"})
	}
	return nil
}

// AddAlertEvent 记录报警事件。
func (s *Store) AddAlertEvent(e model.AlertEvent) error {
	_, err := s.db.Exec(`INSERT INTO alert_event(ts,alert_id,event,value) VALUES(?,?,?,?)`,
		e.Ts, e.AlertID, e.Event, e.Value)
	return err
}

// ListActiveAlerts 列出未消除报警。clusterID 为空则所有集群。
func (s *Store) ListActiveAlerts(clusterID string) ([]model.Alert, error) {
	q := `SELECT id,cluster_id,cluster_name,node_name,object_type,object_id,object_name,metric,threshold,
		recovered,acknowledged,first_trigger_ts,last_trigger_ts,recover_ts,ack_ts,eliminated_ts,last_value
		FROM alert WHERE eliminated_ts=0`
	args := []interface{}{}
	if clusterID != "" {
		q += ` AND cluster_id=?`
		args = append(args, clusterID)
	}
	q += ` ORDER BY first_trigger_ts DESC`
	rows, err := s.db.Query(q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.Alert
	for rows.Next() {
		var a model.Alert
		if err := rows.Scan(&a.ID, &a.ClusterID, &a.ClusterName, &a.NodeName, &a.ObjectType, &a.ObjectID, &a.ObjectName, &a.Metric, &a.Threshold,
			&a.Recovered, &a.Acknowledged, &a.FirstTriggerTs, &a.LastTriggerTs, &a.RecoverTs, &a.AckTs, &a.EliminatedTs, &a.LastValue); err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

// CountActiveAlerts 统计未消除报警数（供侧边栏角标）。clusterID 为空则全部。
func (s *Store) CountActiveAlerts(clusterID string) (int, error) {
	q := `SELECT COUNT(*) FROM alert WHERE eliminated_ts=0`
	args := []interface{}{}
	if clusterID != "" {
		q += ` AND cluster_id=?`
		args = append(args, clusterID)
	}
	var n int
	err := s.db.QueryRow(q, args...).Scan(&n)
	return n, err
}
