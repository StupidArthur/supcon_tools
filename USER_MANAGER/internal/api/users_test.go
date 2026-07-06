package api

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// makeEnvelope 构造平台标准响应 envelope。
// content 可为 nil（写操作响应）。
func makeEnvelope(code, msg string, content any) []byte {
	type env struct {
		Code    string `json:"code"`
		Msg     string `json:"msg"`
		Content any    `json:"content"`
	}
	e := env{Code: code, Msg: msg, Content: content}
	b, _ := json.Marshal(e)
	return b
}

// newMockServer 返回一个 httptest.Server，对每个 path 响应 handler。
func newMockServer(t *testing.T, handlers map[string]http.HandlerFunc) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	for path, h := range handlers {
		mux.HandleFunc(path, h)
	}
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv
}

func TestLogin_Success(t *testing.T) {
	srv := newMockServer(t, map[string]http.HandlerFunc{
		"/tpt-admin/system-manager/umsAdmin/login": func(w http.ResponseWriter, r *http.Request) {
			// 校验请求体 — 必须有 data 顶层 wrapper（与父级 common/api.py 对齐）
			var body map[string]any
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Errorf("decode body: %v", err)
			}
			data, ok := body["data"].(map[string]any)
			if !ok {
				t.Fatalf("body missing 'data' wrapper: %+v", body)
			}
			if data["username"] != "admin" {
				t.Errorf("username = %v, want admin", data["username"])
			}
			if data["accountType"] != "0" {
				t.Errorf("accountType = %v, want 0", data["accountType"])
			}
			w.Header().Set("Content-Type", "application/json")
			w.Write(makeEnvelope("00000", "OK", map[string]string{"token": "tok-abc"}))
		},
	})

	c := NewClient(srv.URL)
	if err := c.Login(context.Background(), "admin", "pwd", ""); err != nil {
		t.Fatalf("login: %v", err)
	}
	if c.Token() != "tok-abc" {
		t.Errorf("token = %q, want tok-abc", c.Token())
	}
	if !c.IsLoggedIn() {
		t.Error("IsLoggedIn = false, want true")
	}
}

func TestLogin_HTTPS_TenantCookie(t *testing.T) {
	var gotCookie string
	srv := newMockServer(t, map[string]http.HandlerFunc{
		"/tpt-admin/system-manager/umsAdmin/login": func(w http.ResponseWriter, r *http.Request) {
			gotCookie = r.Header.Get("Cookie")
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			data, ok := body["data"].(map[string]any)
			if !ok {
				t.Fatalf("body missing 'data' wrapper: %+v", body)
			}
			if data["tenantId"] != "TENANT1" {
				t.Errorf("tenantId in body = %v, want TENANT1", data["tenantId"])
			}
			w.Header().Set("Content-Type", "application/json")
			w.Write(makeEnvelope("00000", "OK", map[string]string{"token": "tok-xyz"}))
		},
	})

	// 模拟 HTTPS 场景：baseURL 以 https:// 开头（HTTPS mode 由 caller 决定）
	// httptest 默认是 http://，所以这里只验证 body 字段被设置；cookie 在真 HTTPS 才注入
	c := NewClient(srv.URL)
	if err := c.Login(context.Background(), "admin", "pwd", "TENANT1"); err != nil {
		t.Fatalf("login: %v", err)
	}
	// 这里 httptest 是 http，所以 cookie 不应被注入
	if strings.Contains(gotCookie, "TptSaasUserTenantryId") {
		t.Errorf("cookie injected on http (should only on https): %s", gotCookie)
	}
	if c.TenantID() != "TENANT1" {
		t.Errorf("TenantID = %q, want TENANT1", c.TenantID())
	}
}

func TestLogin_AuthError(t *testing.T) {
	srv := newMockServer(t, map[string]http.HandlerFunc{
		"/tpt-admin/system-manager/umsAdmin/login": func(w http.ResponseWriter, r *http.Request) {
			w.Write(makeEnvelope("A0230", "登录已超时", nil))
		},
	})
	c := NewClient(srv.URL)
	err := c.Login(context.Background(), "u", "p", "")
	if !IsAuthError(err) {
		t.Fatalf("expected ErrAuthError, got %T: %v", err, err)
	}
}

func TestListUsers_Success(t *testing.T) {
	srv := newMockServer(t, map[string]http.HandlerFunc{
		"/tpt-admin/system-manager/umsAdmin/login": func(w http.ResponseWriter, r *http.Request) {
			w.Write(makeEnvelope("00000", "OK", map[string]string{"token": "tok-abc"}))
		},
		"/xpt-system/api/system-manager/umsAdmin/listByOrgId": func(w http.ResponseWriter, r *http.Request) {
			// 校验 Bearer header
			if got := r.Header.Get("Authorization"); got != "Bearer tok-abc" {
				t.Errorf("Authorization = %q, want Bearer tok-abc", got)
			}
			content := PageResponse{
				Records: []User{
					{ID: 1, Username: "admin", NickName: "管理员", Status: 0, Type: 0},
					{ID: 2, Username: "tpt", NickName: "tpt", Status: 0, Type: 2},
				},
				Total:   2,
				Size:    10,
				Current: 1,
				Pages:   1,
			}
			w.Write(makeEnvelope("00000", "OK", content))
		},
	})

	c := NewClient(srv.URL)
	if err := c.Login(context.Background(), "admin", "pwd", ""); err != nil {
		t.Fatalf("Login: %v", err)
	}
	resp, err := c.ListUsers(context.Background(), 1, 10, "", "admin", "")
	if err != nil {
		t.Fatalf("ListUsers: %v", err)
	}
	if len(resp.Records) != 2 {
		t.Errorf("records count = %d, want 2", len(resp.Records))
	}
	if resp.Records[0].Username != "admin" {
		t.Errorf("first username = %q, want admin", resp.Records[0].Username)
	}
}

func TestListUsers_AutoPaginate(t *testing.T) {
	var calls int
	srv := newMockServer(t, map[string]http.HandlerFunc{
		"/tpt-admin/system-manager/umsAdmin/login": func(w http.ResponseWriter, r *http.Request) {
			w.Write(makeEnvelope("00000", "OK", map[string]string{"token": "tok-abc"}))
		},
		"/xpt-system/api/system-manager/umsAdmin/listByOrgId": func(w http.ResponseWriter, r *http.Request) {
			calls++
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			rb := body["requestBase"].(map[string]any)
			pageSize := rb["page"].(string)
			// 第一次返回 3 条，第二次返回 1 条 (小于 pageSize=3) 触发停止
			if calls == 1 {
				content := PageResponse{
					Records: []User{
						{ID: 1}, {ID: 2}, {ID: 3},
					},
					Total:   4,
					Size:    3,
					Current: 1,
					Pages:   2,
				}
				w.Write(makeEnvelope("00000", "OK", content))
			} else {
				if pageSize != "2-3" {
					t.Errorf("page = %q, want 2-3", pageSize)
				}
				content := PageResponse{
					Records: []User{{ID: 4}},
					Total:   4,
					Size:    3,
					Current: 2,
					Pages:   2,
				}
				w.Write(makeEnvelope("00000", "OK", content))
			}
		},
	})

	c := NewClient(srv.URL)
	_ = c.Login(context.Background(), "admin", "pwd", "")
	users, err := c.GetAllUsers(context.Background(), "", "", 3)
	if err != nil {
		t.Fatalf("GetAllUsers: %v", err)
	}
	if len(users) != 4 {
		t.Errorf("users count = %d, want 4", len(users))
	}
	if calls != 2 {
		t.Errorf("calls = %d, want 2", calls)
	}
}

func TestCreateUser_Success(t *testing.T) {
	srv := newMockServer(t, map[string]http.HandlerFunc{
		"/tpt-admin/system-manager/umsAdmin/login": func(w http.ResponseWriter, r *http.Request) {
			w.Write(makeEnvelope("00000", "OK", map[string]string{"token": "tok-abc"}))
		},
		"/xpt-system/api/system-manager/umsAdmin": func(w http.ResponseWriter, r *http.Request) {
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			data := body["data"].(map[string]any)
			if data["username"] != "zhangsan" {
				t.Errorf("username = %v", data["username"])
			}
			// 验证 v1 固定参数
			if data["orgName"] != "默认组织" {
				t.Errorf("orgName = %v", data["orgName"])
			}
			if data["type"] != "2" {
				t.Errorf("type = %v, want 2", data["type"])
			}
			orgIds := data["orgIds"].([]any)
			if orgIds[0].(float64) != 1 {
				t.Errorf("orgIds[0] = %v, want 1", orgIds[0])
			}

			// 响应无 content
			w.Write(makeEnvelope("00000", "Request succeeded", nil))
		},
	})

	c := NewClient(srv.URL)
	_ = c.Login(context.Background(), "admin", "pwd", "")
	st, err := c.CreateUser(context.Background(), UserDraft{
		Username: "zhangsan",
		Password: "Pwd@123",
		NickName: "张三",
		Email:    "z@x.com",
		Phone:    "13800138000",
	})
	if err != nil {
		t.Fatalf("CreateUser: %v", err)
	}
	if st.Code != "00000" {
		t.Errorf("code = %s, want 00000", st.Code)
	}
}

func TestResetPassword_Success(t *testing.T) {
	var gotID float64
	var gotPwd string
	srv := newMockServer(t, map[string]http.HandlerFunc{
		"/tpt-admin/system-manager/umsAdmin/login": func(w http.ResponseWriter, r *http.Request) {
			w.Write(makeEnvelope("00000", "OK", map[string]string{"token": "tok-abc"}))
		},
		"/xpt-system/api/system-manager/umsAdmin/resetPwd": func(w http.ResponseWriter, r *http.Request) {
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			data := body["data"].(map[string]any)
			gotID = data["id"].(float64)
			gotPwd = data["newPwd"].(string)
			if data["newPwd"] != data["confirmPwd"] {
				t.Errorf("newPwd != confirmPwd")
			}
			w.Write(makeEnvelope("00000", "Request succeeded", nil))
		},
	})

	c := NewClient(srv.URL)
	_ = c.Login(context.Background(), "admin", "pwd", "")
	st, err := c.ResetPassword(context.Background(), 474357, "NewPwd@2026")
	if err != nil {
		t.Fatalf("ResetPassword: %v", err)
	}
	if st.Code != "00000" {
		t.Errorf("code = %s", st.Code)
	}
	if gotID != 474357 {
		t.Errorf("id = %v, want 474357", gotID)
	}
	if gotPwd != "NewPwd@2026" {
		t.Errorf("newPwd = %q", gotPwd)
	}
}

func TestIsAuthResponseCode(t *testing.T) {
	tests := []struct {
		code, msg string
		want      bool
	}{
		{"A0230", "", true},
		{"A0201", "登录已超时", true},
		{"00000", "OK", false},
		{"A0400", "参数错误", false},
		{"B0001", "Unauthorized request", true},
		{"X9999", "无访问权限", true},
	}
	for _, tc := range tests {
		got := IsAuthResponseCode(tc.code, tc.msg)
		if got != tc.want {
			t.Errorf("IsAuthResponseCode(%q, %q) = %v, want %v", tc.code, tc.msg, got, tc.want)
		}
	}
}
