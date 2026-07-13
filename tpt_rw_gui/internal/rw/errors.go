package rw

import (
	"errors"
	"strings"

	"github.com/yzc/tpt_api"
)

// PublicError 前端可见的错误。Kind 用于 UI 路由(auth → 回登录;data → 视为空数据)。
type PublicError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
	Kind    string `json:"kind"` // "auth" | "api" | "http" | "parse" | "input" | "data"
}

// KindData 表示"数据空 / 位号不存在"这类语义层错误,binding 层把它视作成功(空响应),
// 不发到前端 toast;前端拿到空切片/空对象,自然渲染为空表。
const KindData = "data"

// Error 实现 error 接口。
func (e *PublicError) Error() string {
	if e.Code != "" {
		return "[" + e.Kind + ":" + e.Code + "] " + e.Message
	}
	return "[" + e.Kind + "] " + e.Message
}

// MapError 把任意 error 翻译成 PublicError。
//
// 优先级:
//  1. 平台业务码 "500" + msg 含"Tag Dose Not Exist" / "Tag Does Not Exist"(平台 typo) → Kind:"data"
//     这是平台在 RT/历史 路径上对不存在位号的标准语义:biz code "500",HTTP 200,
//     在 RT 路径上 tptapi.request 把它当成 TptAPIError 返回。这里判空数据而不是错误。
//  2. auth 码/关键词 → Kind:"auth"
//  3. 其它 tptapi.TptAPIError → Kind:"api"
//  4. 其它含网络/解析关键词 → http / parse
//  5. 兜底 → api
func MapError(err error) *PublicError {
	if err == nil {
		return nil
	}
	var apiErr *tptapi.TptAPIError
	if errors.As(err, &apiErr) {
		if isNonExistentTag(apiErr.Code, apiErr.Msg) {
			return &PublicError{Code: apiErr.Code, Message: apiErr.Msg, Kind: KindData}
		}
		if isAuthCode(apiErr.Code) || isAuthKeyword(apiErr.Msg) {
			return &PublicError{Code: apiErr.Code, Message: apiErr.Msg, Kind: "auth"}
		}
		return &PublicError{Code: apiErr.Code, Message: apiErr.Msg, Kind: "api"}
	}
	msg := err.Error()
	switch {
	case strings.HasPrefix(msg, "登录失败:") || strings.HasPrefix(msg, "登录响应"):
		return &PublicError{Message: msg, Kind: "auth"}
	case strings.HasPrefix(msg, "http "), strings.HasPrefix(msg, "HTTP "):
		return &PublicError{Message: msg, Kind: "http"}
	case strings.Contains(msg, "响应非 JSON"), strings.Contains(msg, "解析失败"):
		return &PublicError{Message: msg, Kind: "parse"}
	default:
		return &PublicError{Message: msg, Kind: "api"}
	}
}

var authCodes = map[string]bool{"A0230": true, "A0201": true, "A0202": true, "A0203": true}

func isAuthCode(code string) bool { return authCodes[code] }

func isAuthKeyword(msg string) bool {
	for _, kw := range []string{"未登录", "登录已超时", "登录过期", "token过期", "无访问权限", "Unauthorized"} {
		if strings.Contains(msg, kw) {
			return true
		}
	}
	return false
}

// isNonExistentTag 平台"位号不存在"的语义层识别。
// 实测在 /tag-value/getRTValue 与 /tag-value/getHistoryValueFromDB 上,
// 平台返 HTTP 200 + body {code:"500", msg:"Tag Dose Not Exist"} 这种形态。
// "Dose" 是平台真实 typo(README 文档之外仍有),所以兜底两个拼写。
func isNonExistentTag(code, msg string) bool {
	if code != "500" {
		return false
	}
	if strings.Contains(msg, "Tag Dose Not Exist") || strings.Contains(msg, "Tag Does Not Exist") {
		return true
	}
	return false
}
