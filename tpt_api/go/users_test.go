package tptapi

import (
	"context"
	"net/http"
	"strings"
	"testing"
)

func TestListUsers(t *testing.T) {
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		// 检查 adminWhere 字段构造
		body := `{"code":"00000","content":{"records":[{"id":1,"username":"u1","nickName":"n1"}],"total":1,"size":10,"current":1,"pages":1}}`
		return fakeResp(200, body), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	c.token = "t"
	resp, err := c.ListUsers(context.Background(), 1, 10, "", "k", "-createTime")
	if err != nil {
		t.Fatalf("ListUsers: %v", err)
	}
	if len(resp.Records) != 1 || resp.Records[0].Username != "u1" {
		t.Errorf("records = %+v", resp.Records)
	}
}

func TestListUsers_EmptyKeyword(t *testing.T) {
	var sentBody string
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		buf, _ := io_ReadAll(r.Body)
		sentBody = string(buf)
		return fakeResp(200, `{"code":"00000","content":{"records":[],"total":0,"size":10,"current":1,"pages":0}}`), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	c.token = "t"
	_, _ = c.ListUsers(context.Background(), 1, 10, "", "", "")
	// 空 keyword 时 adminWhere 应为 {}
	if !strings.Contains(sentBody, `"adminWhere":{}`) {
		t.Errorf("expected empty adminWhere, got body=%s", sentBody)
	}
}

func TestCreateUser_DefaultsApplied(t *testing.T) {
	var sentBody string
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		buf, _ := io_ReadAll(r.Body)
		sentBody = string(buf)
		return fakeResp(200, `{"code":"00000","msg":"OK"}`), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	c.token = "t"
	_, err := c.CreateUser(context.Background(), UserDraft{
		Username: "alice", Password: "p", NickName: "A", Email: "a@x", Phone: "1",
	})
	if err != nil {
		t.Fatalf("CreateUser: %v", err)
	}
	for _, want := range []string{
		`"orgIds":[1]`, `"roleIds":"5"`, `"type":"2"`, `"gender":"1"`, `"orgName":"默认组织"`,
	} {
		if !strings.Contains(sentBody, want) {
			t.Errorf("missing %s in body: %s", want, sentBody)
		}
	}
}

func TestCreateUser_AdminOverride(t *testing.T) {
	var sentBody string
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		buf, _ := io_ReadAll(r.Body)
		sentBody = string(buf)
		return fakeResp(200, `{"code":"00000","msg":"OK"}`), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	c.token = "t"
	_, err := c.CreateUser(context.Background(), UserDraft{
		Username: "bob", Password: "p", NickName: "B",
		Type: "1", OrgIDs: []int{7}, OrgName: "研发部", RoleIDs: "4",
	})
	if err != nil {
		t.Fatalf("CreateUser: %v", err)
	}
	for _, want := range []string{
		`"orgIds":[7]`, `"orgName":"研发部"`, `"type":"1"`, `"roleIds":"4"`,
	} {
		if !strings.Contains(sentBody, want) {
			t.Errorf("missing %s in body: %s", want, sentBody)
		}
	}
}

func TestListRoles(t *testing.T) {
	var sentBody string
	var gotPath string
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		gotPath = r.URL.Path
		buf, _ := io_ReadAll(r.Body)
		sentBody = string(buf)
		return fakeResp(200, `{"code":"00000","content":{"records":[{"id":5,"name":"普通用户角色","code":"normalRole","status":0},{"id":4,"name":"管理员角色","code":"systemRole","status":0}],"total":2,"size":1000,"current":1,"pages":1}}`), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	c.token = "t"
	resp, err := c.ListRoles(context.Background(), "角色", 1, 1000, "")
	if err != nil {
		t.Fatalf("ListRoles: %v", err)
	}
	if gotPath != UserRolePagePath {
		t.Errorf("expected path %s, got %s", UserRolePagePath, gotPath)
	}
	if !strings.Contains(sentBody, `"*name*":"角色"`) {
		t.Errorf("missing name filter in body: %s", sentBody)
	}
	if len(resp.Records) != 2 || resp.Records[0].Name != "普通用户角色" || resp.Records[1].ID != 4 {
		t.Errorf("records = %+v", resp.Records)
	}
}

func TestResetPassword(t *testing.T) {
	var sentBody string
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method != http.MethodPost || !strings.Contains(r.URL.Path, "/resetPwd") {
			t.Errorf("unexpected request: %s %s", r.Method, r.URL.Path)
		}
		buf, _ := io_ReadAll(r.Body)
		sentBody = string(buf)
		return fakeResp(200, `{"code":"00000","msg":"OK"}`), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	c.token = "t"
	_, err := c.ResetPassword(context.Background(), 42, "newPwd")
	if err != nil {
		t.Fatalf("ResetPassword: %v", err)
	}
	if !strings.Contains(sentBody, `"id":42`) || !strings.Contains(sentBody, `"newPwd":"newPwd"`) {
		t.Errorf("unexpected body: %s", sentBody)
	}
}
