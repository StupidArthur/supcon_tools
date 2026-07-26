// Package wecom 实现企业微信群机器人 webhook 客户端。
package wecom

import "fmt"

// WeComError 表示企业微信业务错误 (errcode != 0)。业务错误不重试。
type WeComError struct {
	ErrCode int
	ErrMsg  string
}

func (e *WeComError) Error() string {
	return fmt.Sprintf("[%d] %s", e.ErrCode, e.ErrMsg)
}

// Response 企业微信 send 接口的响应。
type Response struct {
	ErrCode int    `json:"errcode"`
	ErrMsg  string `json:"errmsg"`
}
