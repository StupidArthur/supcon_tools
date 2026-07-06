package batch

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"user-manager/internal/api"
)

func newMockBatchServer(t *testing.T) (*httptest.Server, *int32) {
	t.Helper()
	var counter int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/tpt-admin/system-manager/umsAdmin/login":
			w.Header().Set("Content-Type", "application/json")
			w.Write([]byte(`{"code":"00000","msg":"OK","content":{"token":"tok"}}`))
		case "/xpt-system/api/system-manager/umsAdmin":
			atomic.AddInt32(&counter, 1)
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			data := body["data"].(map[string]any)
			username, _ := data["username"].(string)
			// 模拟：username = "fail_xxx" 返回业务错误，其他成功
			if username == "fail_x" {
				w.Write([]byte(`{"code":"A0400","msg":"invalid username"}`))
				return
			}
			w.Write([]byte(`{"code":"00000","msg":"Request succeeded"}`))
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(srv.Close)
	return srv, &counter
}

func TestBatchCreateUsers_AllSuccess(t *testing.T) {
	srv, counter := newMockBatchServer(t)
	c := api.NewClient(srv.URL)
	if err := c.Login(context.Background(), "admin", "pwd", ""); err != nil {
		t.Fatalf("login: %v", err)
	}

	drafts := []api.UserDraft{
		{Username: "u1", Password: "P1", NickName: "n1"},
		{Username: "u2", Password: "P2", NickName: "n2"},
		{Username: "u3", Password: "P3", NickName: "n3"},
	}
	var progressCalls int32
	var mu sync.Mutex
	var lastProg BatchProgress
	results, err := BatchCreateUsers(context.Background(), c, drafts, 2, func(p BatchProgress) {
		atomic.AddInt32(&progressCalls, 1)
		mu.Lock()
		lastProg = p
		mu.Unlock()
	})
	if err != nil {
		t.Fatalf("BatchCreateUsers: %v", err)
	}
	if len(results) != 3 {
		t.Fatalf("results count = %d, want 3", len(results))
	}
	for i, r := range results {
		if !r.Success {
			t.Errorf("results[%d] failed: %+v", i, r)
		}
	}
	if got := atomic.LoadInt32(counter); got != 3 {
		t.Errorf("create calls = %d, want 3", got)
	}
	if atomic.LoadInt32(&progressCalls) != 3 {
		t.Errorf("progress calls = %d, want 3", progressCalls)
	}
	if !lastProg.Finished {
		t.Errorf("last progress.Finished = false, want true")
	}
	if lastProg.Done != 3 || lastProg.Total != 3 {
		t.Errorf("last progress = %+v", lastProg)
	}
}

func TestBatchCreateUsers_PartialFail(t *testing.T) {
	srv, _ := newMockBatchServer(t)
	c := api.NewClient(srv.URL)
	_ = c.Login(context.Background(), "admin", "pwd", "")

	drafts := []api.UserDraft{
		{Username: "u1", Password: "P1", NickName: "n1"},
		{Username: "fail_x", Password: "P2", NickName: "n2"},
		{Username: "u3", Password: "P3", NickName: "n3"},
	}
	results, err := BatchCreateUsers(context.Background(), c, drafts, 1, nil)
	if err != nil {
		t.Fatalf("BatchCreateUsers: %v", err)
	}
	if len(results) != 3 {
		t.Fatalf("results count = %d, want 3", len(results))
	}
	if !results[0].Success {
		t.Errorf("results[0] should succeed, got %+v", results[0])
	}
	if results[1].Success {
		t.Errorf("results[1] should fail, got %+v", results[1])
	}
	if !results[2].Success {
		t.Errorf("results[2] should succeed, got %+v", results[2])
	}
	if results[1].Code != "A0400" {
		t.Errorf("results[1].code = %q, want A0400", results[1].Code)
	}
}

func TestBatchCreateUsers_ContextCancel(t *testing.T) {
	srv, _ := newMockBatchServer(t)
	c := api.NewClient(srv.URL)
	_ = c.Login(context.Background(), "admin", "pwd", "")

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // 立即取消

	drafts := []api.UserDraft{
		{Username: "u1", Password: "P1", NickName: "n1"},
	}
	_, err := BatchCreateUsers(ctx, c, drafts, 1, nil)
	if !errors.Is(err, context.Canceled) {
		t.Errorf("err = %v, want context.Canceled", err)
	}
}

func TestBatchCreateUsers_ConcurrencyLimit(t *testing.T) {
	// mock 让每个 create 阻塞 50ms；期望 4 个用户 * 2 并发 ≈ 100ms（而非 200ms）
	var inFlight int32
	var maxInFlight int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/tpt-admin/system-manager/umsAdmin/login":
			w.Write([]byte(`{"code":"00000","msg":"OK","content":{"token":"tok"}}`))
		case "/xpt-system/api/system-manager/umsAdmin":
			cur := atomic.AddInt32(&inFlight, 1)
			for {
				m := atomic.LoadInt32(&maxInFlight)
				if cur <= m || atomic.CompareAndSwapInt32(&maxInFlight, m, cur) {
					break
				}
			}
			time.Sleep(50 * time.Millisecond)
			atomic.AddInt32(&inFlight, -1)
			w.Write([]byte(`{"code":"00000","msg":"OK"}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	c := api.NewClient(srv.URL)
	_ = c.Login(context.Background(), "admin", "pwd", "")

	drafts := []api.UserDraft{
		{Username: "u1", Password: "P1", NickName: "n1"},
		{Username: "u2", Password: "P2", NickName: "n2"},
		{Username: "u3", Password: "P3", NickName: "n3"},
		{Username: "u4", Password: "P4", NickName: "n4"},
	}
	start := time.Now()
	_, err := BatchCreateUsers(context.Background(), c, drafts, 2, nil)
	elapsed := time.Since(start)
	if err != nil {
		t.Fatalf("BatchCreateUsers: %v", err)
	}
	if maxInFlight > 2 {
		t.Errorf("maxInFlight = %d, want <= 2", maxInFlight)
	}
	// 4 个 / 2 并发 * 50ms = ~100ms；放宽容差
	if elapsed > 200*time.Millisecond {
		t.Errorf("elapsed = %v, want ~100ms (4 jobs * 50ms / 2 concurrent)", elapsed)
	}
}
