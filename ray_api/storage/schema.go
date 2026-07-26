package storage

const createTablesSQL = `
CREATE TABLE IF NOT EXISTS node_metric(
  ts INTEGER NOT NULL,
  cluster_id TEXT NOT NULL DEFAULT '',
  node_id TEXT NOT NULL,
  hostname TEXT,
  ip TEXT,
  is_head INTEGER,
  state TEXT,
  cpu REAL,
  mem_total INTEGER,
  mem_used INTEGER,
  gpu_total REAL,
  gpu_used REAL,
  is_partial INTEGER
);

CREATE TABLE IF NOT EXISTS worker_snapshot(
  ts INTEGER NOT NULL,
  cluster_id TEXT NOT NULL DEFAULT '',
  node_id TEXT NOT NULL,
  pid INTEGER,
  job_id TEXT,
  process_name TEXT,
  cpu_percent REAL,
  mem_rss INTEGER,
  num_fds INTEGER,
  language TEXT,
  gpu_used REAL
);

CREATE TABLE IF NOT EXISTS actor_snapshot(
  ts INTEGER NOT NULL,
  cluster_id TEXT NOT NULL DEFAULT '',
  node_id TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  actor_class TEXT,
  name TEXT,
  state TEXT,
  num_restarts INTEGER,
  job_id TEXT,
  pid INTEGER,
  ip_address TEXT,
  num_exec_tasks INTEGER,
  gpu_used REAL,
  exit_detail TEXT
);

CREATE TABLE IF NOT EXISTS job_snapshot(
  ts INTEGER NOT NULL,
  cluster_id TEXT NOT NULL DEFAULT '',
  job_id TEXT NOT NULL,
  status TEXT,
  start_time INTEGER,
  end_time INTEGER,
  error_type TEXT,
  entry TEXT
);

CREATE TABLE IF NOT EXISTS cluster_metric(
  ts INTEGER NOT NULL,
  cluster_id TEXT NOT NULL DEFAULT '',
  cpu_total REAL,
  cpu_used REAL,
  mem_total REAL,
  mem_used REAL,
  gpu_total REAL,
  gpu_used REAL,
  heartbeat_max REAL
);

CREATE TABLE IF NOT EXISTS actor_event(
  ts INTEGER NOT NULL,
  cluster_id TEXT NOT NULL DEFAULT '',
  actor_id TEXT NOT NULL,
  actor_class TEXT,
  prev_state TEXT,
  new_state TEXT,
  death_cause TEXT
);

CREATE TABLE IF NOT EXISTS job_event(
  ts INTEGER NOT NULL,
  cluster_id TEXT NOT NULL DEFAULT '',
  job_id TEXT NOT NULL,
  prev_status TEXT,
  new_status TEXT,
  error_type TEXT
);

CREATE TABLE IF NOT EXISTS alert(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cluster_id TEXT NOT NULL DEFAULT '',
  cluster_name TEXT,
  node_name TEXT,
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  object_name TEXT,
  metric TEXT NOT NULL,
  threshold REAL NOT NULL,
  recovered INTEGER DEFAULT 0,
  acknowledged INTEGER DEFAULT 0,
  first_trigger_ts INTEGER NOT NULL,
  last_trigger_ts INTEGER,
  recover_ts INTEGER,
  ack_ts INTEGER,
  eliminated_ts INTEGER,
  last_value REAL
);

CREATE TABLE IF NOT EXISTS alert_event(
  ts INTEGER NOT NULL,
  alert_id INTEGER NOT NULL,
  event TEXT NOT NULL,
  value REAL
);
`

const createIndexesSQL = `
CREATE INDEX IF NOT EXISTS idx_node_ts ON node_metric(cluster_id, node_id, ts);
CREATE INDEX IF NOT EXISTS idx_worker_ts ON worker_snapshot(cluster_id, node_id, ts);
CREATE INDEX IF NOT EXISTS idx_actor_ts ON actor_snapshot(cluster_id, actor_id, ts);
CREATE INDEX IF NOT EXISTS idx_job_ts ON job_snapshot(cluster_id, job_id, ts);
CREATE INDEX IF NOT EXISTS idx_cluster_ts ON cluster_metric(cluster_id, ts);
CREATE INDEX IF NOT EXISTS idx_actor_event_ts ON actor_event(cluster_id, ts);
CREATE INDEX IF NOT EXISTS idx_job_event_ts ON job_event(cluster_id, ts);
CREATE INDEX IF NOT EXISTS idx_alert_active ON alert(cluster_id, eliminated_ts);
CREATE INDEX IF NOT EXISTS idx_alert_object ON alert(cluster_id, object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_alert_event ON alert_event(alert_id, ts);

CREATE INDEX IF NOT EXISTS idx_node_cleanup_ts ON node_metric(ts);
CREATE INDEX IF NOT EXISTS idx_worker_cleanup_ts ON worker_snapshot(ts);
CREATE INDEX IF NOT EXISTS idx_actor_cleanup_ts ON actor_snapshot(ts);
CREATE INDEX IF NOT EXISTS idx_job_cleanup_ts ON job_snapshot(ts);
CREATE INDEX IF NOT EXISTS idx_cluster_cleanup_ts ON cluster_metric(ts);
`

const (
	migrateAddClusterID = "ALTER TABLE %s ADD COLUMN cluster_id TEXT NOT NULL DEFAULT ''"
)

var tablesNeedingClusterID = []string{
	"node_metric", "worker_snapshot", "actor_snapshot", "job_snapshot",
	"cluster_metric", "actor_event", "job_event", "alert",
}

func (s *Store) createSchema() error {
	if _, err := s.db.Exec(createTablesSQL); err != nil {
		return err
	}
	if err := s.migrateClusterID(); err != nil {
		return err
	}
	if has, err := s.hasColumn("worker_snapshot", "gpu_used"); err != nil {
		return err
	} else if !has {
		if _, err := s.db.Exec("ALTER TABLE worker_snapshot ADD COLUMN gpu_used REAL"); err != nil {
			return err
		}
	}
	if has, err := s.hasColumn("worker_snapshot", "process_name"); err != nil {
		return err
	} else if !has {
		if _, err := s.db.Exec("ALTER TABLE worker_snapshot ADD COLUMN process_name TEXT"); err != nil {
			return err
		}
	}
	for _, col := range []string{"cluster_name", "node_name"} {
		if has, err := s.hasColumn("alert", col); err != nil {
			return err
		} else if !has {
			if _, err := s.db.Exec("ALTER TABLE alert ADD COLUMN " + col + " TEXT"); err != nil {
				return err
			}
		}
	}
	if _, err := s.db.Exec(createIndexesSQL); err != nil {
		return err
	}
	return nil
}
