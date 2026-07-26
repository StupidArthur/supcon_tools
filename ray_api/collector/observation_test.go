package collector

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"raymonitor/logx"
)

func TestRayObservationLogsSchemaWithoutCookieOrDynamicActorID(t *testing.T) {
	// Schema 观测默认关闭，此测试验证其行为，显式开启。
	t.Setenv("RAY_MONITOR_OBSERVE_SCHEMA", "1")
	const secretCookie = "session=top-secret"
	const actorID = "dynamic-actor-id-123"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Cookie") != secretCookie {
			t.Errorf("cookie not sent to Ray server")
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Server", "ray-dashboard-test")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"result": true,
			"data": map[string]any{
				"detail": map[string]any{
					"actors": map[string]any{
						actorID: map[string]any{"state": "ALIVE", "pid": 42},
					},
				},
			},
		})
	}))
	t.Cleanup(server.Close)

	dir := t.TempDir()
	if _, err := logx.Init(dir); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(logx.Close)

	opts := CollectorOpts{ClusterID: "prod", PlatformURL: server.URL, Cookie: secretCookie}
	client := NewClient(opts)
	if _, err := client.get(context.Background(), "/nodes/node-secret"); err != nil {
		t.Fatal(err)
	}
	logx.Close()

	date := time.Now().Format("2006-01-02")
	apiLog, err := os.ReadFile(filepath.Join(dir, "api_"+date+".jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	envLog, err := os.ReadFile(filepath.Join(dir, "environment_"+date+".jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	combined := string(apiLog) + string(envLog)
	if strings.Contains(combined, secretCookie) {
		t.Fatal("cookie leaked into observation logs")
	}
	if strings.Contains(combined, actorID) {
		t.Fatal("dynamic actor ID leaked into schema log")
	}
	if !strings.Contains(string(envLog), `$.data.detail.actors.*.state:string`) {
		t.Fatalf("actor schema wildcard missing: %s", envLog)
	}
	if !strings.Contains(string(apiLog), `"/nodes/{nodeId}"`) {
		t.Fatalf("node endpoint was not normalized: %s", apiLog)
	}
}
