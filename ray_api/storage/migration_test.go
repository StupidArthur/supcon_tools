package storage

import (
	"database/sql"
	"path/filepath"
	"testing"

	"raymonitor/model"
)

func TestOpenMigratesV1SchemaBeforeCreatingIndexes(t *testing.T) {
	path := filepath.Join(t.TempDir(), "v1.db")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	v1 := `
CREATE TABLE node_metric(ts INTEGER NOT NULL,node_id TEXT NOT NULL,hostname TEXT,ip TEXT,is_head INTEGER,state TEXT,cpu REAL,mem_total INTEGER,mem_used INTEGER,gpu_total REAL,gpu_used REAL,is_partial INTEGER);
CREATE TABLE worker_snapshot(ts INTEGER NOT NULL,node_id TEXT NOT NULL,pid INTEGER,job_id TEXT,cpu_percent REAL,mem_rss INTEGER,num_fds INTEGER,language TEXT);
CREATE TABLE actor_snapshot(ts INTEGER NOT NULL,node_id TEXT NOT NULL,actor_id TEXT NOT NULL,actor_class TEXT,name TEXT,state TEXT,num_restarts INTEGER,job_id TEXT,pid INTEGER,ip_address TEXT,num_exec_tasks INTEGER,gpu_used REAL,exit_detail TEXT);
CREATE TABLE job_snapshot(ts INTEGER NOT NULL,job_id TEXT NOT NULL,status TEXT,start_time INTEGER,end_time INTEGER,error_type TEXT,entry TEXT);
CREATE TABLE cluster_metric(ts INTEGER NOT NULL,cpu_total REAL,cpu_used REAL,mem_total REAL,mem_used REAL,gpu_total REAL,gpu_used REAL,heartbeat_max REAL);
CREATE TABLE actor_event(ts INTEGER NOT NULL,actor_id TEXT NOT NULL,actor_class TEXT,prev_state TEXT,new_state TEXT,death_cause TEXT);
CREATE TABLE job_event(ts INTEGER NOT NULL,job_id TEXT NOT NULL,prev_status TEXT,new_status TEXT,error_type TEXT);
CREATE TABLE alert(id INTEGER PRIMARY KEY AUTOINCREMENT,object_type TEXT NOT NULL,object_id TEXT NOT NULL,object_name TEXT,metric TEXT NOT NULL,threshold REAL NOT NULL,recovered INTEGER DEFAULT 0,acknowledged INTEGER DEFAULT 0,first_trigger_ts INTEGER NOT NULL,last_trigger_ts INTEGER,recover_ts INTEGER,ack_ts INTEGER,eliminated_ts INTEGER,last_value REAL);
CREATE TABLE alert_event(ts INTEGER NOT NULL,alert_id INTEGER NOT NULL,event TEXT NOT NULL,value REAL);
INSERT INTO node_metric(ts,node_id,hostname,ip,is_head,state,cpu,mem_total,mem_used,gpu_total,gpu_used,is_partial)
VALUES(100,'old-node','old-host','127.0.0.1',0,'ALIVE',1,100,50,0,0,0);
`
	if _, err := db.Exec(v1); err != nil {
		t.Fatalf("create v1 schema: %v", err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}

	store, err := Open(path)
	if err != nil {
		t.Fatalf("open migrated store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })

	for _, table := range tablesNeedingClusterID {
		assertColumn(t, store.db, table, "cluster_id")
	}
	for _, tc := range []struct{ table, column string }{
		{"worker_snapshot", "gpu_used"},
		{"worker_snapshot", "process_name"},
		{"alert", "cluster_name"},
		{"alert", "node_name"},
	} {
		assertColumn(t, store.db, tc.table, tc.column)
	}
	for _, index := range []string{
		"idx_node_ts", "idx_worker_ts", "idx_actor_ts", "idx_job_ts", "idx_cluster_ts",
		"idx_actor_event_ts", "idx_job_event_ts", "idx_alert_active", "idx_alert_object", "idx_alert_event",
		"idx_node_cleanup_ts", "idx_worker_cleanup_ts", "idx_actor_cleanup_ts", "idx_job_cleanup_ts", "idx_cluster_cleanup_ts",
	} {
		assertIndex(t, store.db, index)
	}

	old, err := store.QueryNodeHistory("", "old-node", 0, 200)
	if err != nil || len(old) != 1 {
		t.Fatalf("old data after migration: rows=%d err=%v", len(old), err)
	}
	if err := store.WriteNodeMetrics("new-cluster", []model.NodeMetric{{Ts: 200, NodeID: "new-node", Hostname: "new-host"}}); err != nil {
		t.Fatalf("write new data: %v", err)
	}
	rows, err := store.QueryNodeHistory("new-cluster", "new-node", 0, 300)
	if err != nil || len(rows) != 1 {
		t.Fatalf("query new data: rows=%d err=%v", len(rows), err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	reopened, err := Open(path)
	if err != nil {
		t.Fatalf("idempotent reopen: %v", err)
	}
	if err := reopened.Close(); err != nil {
		t.Fatal(err)
	}
}

func assertColumn(t *testing.T, db *sql.DB, table, column string) {
	t.Helper()
	rows, err := db.Query("PRAGMA table_info(" + table + ")")
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	for rows.Next() {
		var cid, notNull, pk int
		var name, kind string
		var defaultValue sql.NullString
		if err := rows.Scan(&cid, &name, &kind, &notNull, &defaultValue, &pk); err != nil {
			t.Fatal(err)
		}
		if name == column {
			return
		}
	}
	t.Fatalf("%s.%s missing", table, column)
}

func assertIndex(t *testing.T, db *sql.DB, name string) {
	t.Helper()
	var found string
	err := db.QueryRow("SELECT name FROM sqlite_master WHERE type='index' AND name=?", name).Scan(&found)
	if err != nil {
		t.Fatalf("index %s missing: %v", name, err)
	}
}
