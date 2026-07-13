package session

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/yzc/tpt_api"
)

// fakeTptServer 构造一个最小化的 TPT http 服务端,只应答登录 + 一个空响应。
// 仅用于校验登录码流,业务接口不深入。
func fakeTptServer(t *testing.T, loginCode, loginMsg string) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/login") {
			w.Header().Set("Content-Type", "application/json")
			// 含 token=ok 的 00000 响应
			_, _ = w.Write([]byte(`{"code":"` + loginCode + `","msg":"` + loginMsg + `","content":{"token":"tkn"},"isSuccess":true}`))
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"code":"00000","msg":"ok","content":{}}`))
	}))
}

func TestLogin_OK(t *testing.T) {
	srv := fakeTptServer(t, "00000", "ok")
	defer srv.Close()
	svc := NewService(tptapi.NewService())
	info, err := svc.Login(context.Background(), srv.URL, "u", "p", "", 5)
	if err != nil {
		t.Fatalf("login: %v", err)
	}
	if !info.LoggedIn {
		t.Fatalf("want LoggedIn, got %+v", info)
	}
	if info.URL == "" {
		t.Fatalf("want URL, got empty")
	}
}

func TestLogin_BadCredentials(t *testing.T) {
	// 用一个返回非 00000 的登录码的服务器
	srv := fakeTptServer(t, "A0230", "登录已超时")
	defer srv.Close()
	svc := NewService(tptapi.NewService())
	_, err := svc.Login(context.Background(), srv.URL, "u", "wrong", "", 5)
	if err == nil {
		t.Fatalf("want error on bad credentials")
	}
}

func TestStatus_BeforeLogin(t *testing.T) {
	svc := NewService(tptapi.NewService())
	got := svc.Status(context.Background())
	if got.LoggedIn {
		t.Fatalf("want not logged in")
	}
}


