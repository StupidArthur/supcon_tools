package api

import (
	"errors"
	"fmt"
	"net/http"
	"strings"
)

// ErrAuthError 表示鉴权失败（登录态过期、token 无效等）。
// 由 _request 在 code ∈ {A0230,A0201,A0202,A0203} 或 msg 命中关键词时返回。
type ErrAuthError struct {
	Code string
	Msg  string
}

func (e *ErrAuthError) Error() string {
	return fmt.Sprintf("[%s] %s", e.Code, e.Msg)
}

// IsAuthError 判断 err 是否为鉴权错误。
func IsAuthError(err error) bool {
	var ae *ErrAuthError
	return errors.As(err, &ae)
}

// ErrAPI 是平台返回的业务错误（非鉴权类），如 A0400 参数错误等。
type ErrAPI struct {
	Code string
	Msg  string
}

func (e *ErrAPI) Error() string {
	return fmt.Sprintf("[%s] %s", e.Code, e.Msg)
}

// ErrHTTP 是 HTTP 层错误（4xx/5xx 非业务响应）。
type ErrHTTP struct {
	StatusCode int
	Body       string
}

func (e *ErrHTTP) Error() string {
	return fmt.Sprintf("HTTP %d: %s", e.StatusCode, truncate(e.Body, 200))
}

// 鉴权码集合（与 common/api.py:30 对齐）。
var authCodes = map[string]bool{
	"A0230": true,
	"A0201": true,
	"A0202": true,
	"A0203": true,
}

// 鉴权关键词（与 common/api.py:34 对齐）。
var authKeywords = []string{
	"未登录", "登录已超时", "登录过期", "token过期", "无访问权限", "Unauthorized",
}

// IsAuthResponseCode 判断平台响应 code 是否为鉴权错误。
func IsAuthResponseCode(code, msg string) bool {
	if authCodes[code] {
		return true
	}
	for _, kw := range authKeywords {
		if strings.Contains(msg, kw) {
			return true
		}
	}
	return false
}

// classifyStatus 把非 2xx HTTP 响应包成 ErrHTTP。
func classifyStatus(resp *http.Response, body []byte) error {
	return &ErrHTTP{
		StatusCode: resp.StatusCode,
		Body:       string(body),
	}
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "..."
}
