package api

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// Client 是 TPT 后台域的 HTTP 客户端。
// 同一 Client 实例持有 token + cookies，所有方法共用。
// 不并发安全（http.Client 本身并发安全，但 cookies/headers 字段在并发场景需外层加锁）。
type Client struct {
	baseURL string
	hc      *http.Client

	// 鉴权态：login 后写入
	token string

	// HTTPS 多租户登录需要的 cookie；login 时由 caller 决定是否设置
	tenantID string
}

// 业务默认值，可按需改写。
const (
	defaultTimeout = 30 * time.Second

	// accountType 写死 "0"，与父级 common/api.py:38 一致。
	loginAccountType = "0"

	// 登录端点（与父级 common/api.py:52 一致）
	loginPath = "/tpt-admin/system-manager/umsAdmin/login"

	// 业务成功 code
	successCode = "00000"
)

// NewClient 构造一个未登录的 Client。
// baseURL 例：https://supcontpt.supcon.com
func NewClient(baseURL string) *Client {
	c := &Client{
		baseURL: strings.TrimRight(baseURL, "/"),
		hc: &http.Client{
			Timeout: defaultTimeout,
		},
	}
	return c
}

// BaseURL 返回当前 base URL（去掉末尾 /）。
func (c *Client) BaseURL() string { return c.baseURL }

// Token 返回当前 token（未登录时为空）。
func (c *Client) Token() string { return c.token }

// TenantID 返回当前租户 ID。
func (c *Client) TenantID() string { return c.tenantID }

// IsLoggedIn 是否有可用 token。
func (c *Client) IsLoggedIn() bool { return c.token != "" }

// Logout 清空登录态。
func (c *Client) Logout() {
	c.token = ""
}

// Login 用账号密码登录 TPT 后台。
//   - tenantID 为空时不发 tenantId body 字段也不设 cookie（HTTP 单租户场景）
//   - tenantID 非空时（HTTPS 多租户）会发 tenantId body 字段，并设 TptSaasUserTenantryId / tenant-id cookie
//
// 成功返回 nil；token 自动注入，后续方法自动带 Bearer。
//
// 平台端点要求 body 包成 {"data": {...}}，与父级 common/api.py 的 _request(wrap=True) 一致。
// 重要：login body 必须包 data 顶层键，否则平台报 A0400 「用户请求参数错误」。
func (c *Client) Login(ctx context.Context, username, password, tenantID string) error {
	c.tenantID = tenantID

	innerBody := map[string]any{
		"username":     username,
		"password":     password,
		"remember":     false,
		"accountType":  loginAccountType,
		"generateCode": false,
	}
	if tenantID != "" {
		innerBody["tenantId"] = tenantID
	}
	body := map[string]any{"data": innerBody}

	var resp LoginResponse
	if err := c.doRequest(ctx, loginPath, body, &resp, true /* hasContent */); err != nil {
		return err
	}
	if resp.Token == "" {
		return &ErrAPI{Code: "EMPTY", Msg: "login response missing token"}
	}
	c.token = resp.Token

	// HTTPS 多租户：登录成功后写 tpt-token cookie（Wails 绑定层如需可读）
	// 这里只保留 token 字段，不维护 cookie jar；HTTP 层每次请求带 Bearer header 即可
	return nil
}

// doRequest 是核心 HTTP 调用，被 Login / ListUsers / CreateUser / ResetPassword 复用。
//
// hasContent=true: 期望响应有 content 字段，把 content 解码到 out（type 为 *struct）
// hasContent=false: 期望响应是 OperationStatus（无 content，整体解码到 out）
func (c *Client) doRequest(ctx context.Context, path string, body any, out any, hasContent bool) error {
	u := c.baseURL + "/" + strings.TrimLeft(path, "/")

	jsonBody, err := json.Marshal(body)
	if err != nil {
		return fmt.Errorf("marshal body: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, u, bytes.NewReader(jsonBody))
	if err != nil {
		return fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Accept-Language", "zh-CN")

	// Bearer token（登录后所有请求都带）
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}

	// HTTPS 多租户：每次请求都带 cookie（兼容服务端从 cookie 读租户的场景）
	if c.tenantID != "" && strings.HasPrefix(c.baseURL, "https://") {
		req.Header.Set("Cookie", fmt.Sprintf("TptSaasUserTenantryId=%s; tenant-id=%s", c.tenantID, c.tenantID))
	}

	resp, err := c.hc.Do(req)
	if err != nil {
		return fmt.Errorf("http do: %w", err)
	}
	defer resp.Body.Close()

	rawBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("read body: %w", err)
	}

	// HTTP 状态码异常
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return classifyStatus(resp, rawBody)
	}

	// 业务层响应
	var envelope struct {
		Code     string          `json:"code"`
		Msg      string          `json:"msg"`
		Content  json.RawMessage `json:"content"`
		Success  bool            `json:"success"`
	}
	if err := json.Unmarshal(rawBody, &envelope); err != nil {
		return fmt.Errorf("decode envelope: %w (raw: %s)", err, truncate(string(rawBody), 200))
	}

	// 鉴权错误特殊处理（前端可据此触发重新登录）
	if IsAuthResponseCode(envelope.Code, envelope.Msg) {
		return &ErrAuthError{Code: envelope.Code, Msg: envelope.Msg}
	}

	// 业务 code != 00000 视为失败
	if envelope.Code != successCode {
		return &ErrAPI{Code: envelope.Code, Msg: envelope.Msg}
	}

	// 解码 content（或整体）到 out
	if hasContent {
		if len(envelope.Content) == 0 {
			return fmt.Errorf("response missing content (code=%s)", envelope.Code)
		}
		if err := json.Unmarshal(envelope.Content, out); err != nil {
			return fmt.Errorf("decode content: %w", err)
		}
	} else {
		if err := json.Unmarshal(rawBody, out); err != nil {
			return fmt.Errorf("decode body: %w", err)
		}
	}
	return nil
}
