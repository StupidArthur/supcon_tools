// Package integration 跨包真实链路测试。
//
// 走"httptest fake server → *tptapi.Service.Login → rw.NewTptClientAdapter → rw.Service → RWBinding"完整路径。
// 不依赖 app.NewContainer,因为 Container 内部会构造独立的 tptapi.Service(连不上本测试后端)。
package integration_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/yzc/tpt_api"

	"tpt_rw_gui/internal/bindings"
	"tpt_rw_gui/internal/rw"
	"tpt_rw_gui/internal/session"
)

// fakeServer 模拟 TPT 后端,只应答本测试用例涉及的端点。
// 全部走 00000 + 一些 fixture 数据。
func fakeServer(t *testing.T) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.HasSuffix(r.URL.Path, "/login"):
			_, _ = w.Write([]byte(`{"code":"00000","msg":"ok","content":{"token":"eyJ.eyJ.signature"},"isSuccess":true}`))
		case strings.HasSuffix(r.URL.Path, "/ds-info/page"):
			_, _ = w.Write([]byte(`{"code":"00000","msg":"ok","content":{"records":[{"id":9,"dsName":"opcua-sim","dsTarUrl":"opc.tcp://h:18950","dsType":1,"dsSubType":4,"alive":true,"dsStatus":1}]},"isSuccess":true}`))
		case strings.HasSuffix(r.URL.Path, "/tag-group/queryWithQuality"):
			_, _ = w.Write([]byte(`{"code":"00000","msg":"ok","content":{"records":[{"id":1,"tagName":"demo.t_double","tagBaseName":"1_demo.t_double","dataType":11,"tagType":1,"dsId":9,"tagValue":3.14,"tagTime":"2026-07-13 12:00:00","quality":0,"groupName":"Root"}]},"isSuccess":true}`))
		case strings.HasSuffix(r.URL.Path, "/tag-value/getRTValue"):
			_, _ = w.Write([]byte(`{"code":"00000","msg":"ok","content":[{"tagName":"demo.t_double","tagValue":7.5,"tagTime":"2026-07-13 12:00:01","appTime":"2026-07-13 12:00:01","quality":0,"dataType":11,"dsId":9,"isSuccess":true}],"isSuccess":true}`))
		case strings.HasSuffix(r.URL.Path, "/tag-value/writeTagValues"):
			_, _ = w.Write([]byte(`{"code":"00000","msg":"ok","content":{},"isSuccess":true}`))
		case strings.HasSuffix(r.URL.Path, "/tag-value/getHistoryValueFromDB"):
			_, _ = w.Write([]byte(`{"code":"00000","msg":"ok","content":[{"tagName":"demo.t_double","tagValue":7.5,"appTime":"2026-07-13 12:00:01","quality":0}],"isSuccess":true}`))
		default:
			_, _ = w.Write([]byte(`{"code":"A0999","msg":"unhandled ` + r.URL.Path + `"}`))
		}
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv
}

// makeBindings 起一个"已登录"tptapi.Service,再上 rw + bindings。
func makeBindings(t *testing.T, srvURL string) *bindings.RWBinding {
	t.Helper()
	svc := tptapi.NewService()
	if _, err := svc.Login(srvURL, "u", "p", "", 5*time.Second); err != nil {
		t.Fatalf("service.Login: %v", err)
	}
	sess := session.NewService(svc)
	port := rw.NewTptClientAdapter(svc)
	rwSvc := rw.NewService(port)

	rwBinding := bindings.NewRWBinding(sess, rwSvc)
	rwBinding.SetContext(context.Background())
	return rwBinding
}

func TestIntegration_EndToEnd(t *testing.T) {
	srv := fakeServer(t)
	b := makeBindings(t, srv.URL)

	// 1. ListDataSources
	got, err := b.ListDataSources()
	if err != nil {
		t.Fatalf("ListDataSources: %v", err)
	}
	if len(got) != 1 || got[0].Name != "opcua-sim" {
		t.Fatalf("ListDataSources want 1 opcua-sim, got %+v", got)
	}

	// 2. ListTags
	dsID := 9
	tags, err := b.ListTags(bindings.ListTagsRequestDTO{DSID: &dsID, Keyword: "demo", PageSize: 20})
	if err != nil {
		t.Fatalf("ListTags: %v", err)
	}
	if len(tags) != 1 || tags[0].Name != "demo.t_double" {
		t.Fatalf("ListTags want 1 demo.t_double, got %+v", tags)
	}

	// 3. ReadRealtime
	rt, err := b.ReadRealtime([]string{"demo.t_double"})
	if err != nil {
		t.Fatalf("ReadRealtime: %v", err)
	}
	if len(rt) != 1 || rt[0].TagName != "demo.t_double" || rt[0].Value != "7.5" {
		t.Fatalf("ReadRealtime want demo.t_double=7.5, got %+v", rt)
	}

	// 4. WriteValues + readback
	res, err := b.WriteValues(bindings.WriteRequestDTO{
		Values:          map[string]any{"demo.t_double": 7.5},
		ReadbackDelayMs: 5,
	})
	if err != nil {
		t.Fatalf("WriteValues: %v", err)
	}
	if len(res.Readback) != 1 || res.Readback[0].Value != "7.5" {
		t.Fatalf("WriteValues readback want 7.5, got %+v", res.Readback)
	}

	// 5. ReadHistory fromdb
	hist, err := b.ReadHistory(bindings.ReadHistoryRequestDTO{
		TagNames: []string{"demo.t_double"},
		BegTime:  "2026-07-13 00:00:00",
		EndTime:  "2026-07-13 23:59:59",
		Mode:     "fromdb",
	})
	if err != nil {
		t.Fatalf("ReadHistory: %v", err)
	}
	if len(hist) != 1 || hist[0].TagName != "demo.t_double" || hist[0].Value != "7.5" {
		t.Fatalf("ReadHistory want 1 row 7.5, got %+v", hist)
	}
}

func TestIntegration_AuthError_ReturnsPublicError(t *testing.T) {
	// 改后端:登录后访问都返回 A0230;验证 RWBinding 把它翻译成 PublicError{DTO}{Kind:auth}。
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if strings.HasSuffix(r.URL.Path, "/login") {
			_, _ = w.Write([]byte(`{"code":"00000","msg":"ok","content":{"token":"eyJ.eyJ.signature"},"isSuccess":true}`))
			return
		}
		_, _ = w.Write([]byte(`{"code":"A0230","msg":"登录已超时","content":{},"isSuccess":false}`))
	}))
	t.Cleanup(srv.Close)

	b := makeBindings(t, srv.URL)
	_, err := b.ListDataSources()
	if err == nil {
		t.Fatalf("want error")
	}
	pe, ok := err.(*bindings.PublicErrorDTO)
	if !ok {
		t.Fatalf("want *PublicErrorDTO, got %T %v", err, err)
	}
	if pe.Kind != "auth" {
		t.Fatalf("want kind auth, got %s", pe.Kind)
	}
}

// 确保用到 encoding/json(避免 import 警告)。
var _ = json.Marshal
