package bindings

import (
	"context"
	"time"

	"tpt_rw_gui/internal/session"
)

// SessionBinding 暴露给前端的登录态操作。
type SessionBinding struct {
	ctx context.Context
	svc *session.Service
}

// NewSessionBinding 创建 SessionBinding。
func NewSessionBinding(svc *session.Service) *SessionBinding {
	return &SessionBinding{svc: svc}
}

// SetContext 由 Lifecycle.Startup 注入应用根 ctx。
func (b *SessionBinding) SetContext(ctx context.Context) { b.ctx = ctx }

// LoginRequestDTO 登录请求。
type LoginRequestDTO struct {
	URL       string `json:"url"`
	Username  string `json:"username"`
	Password  string `json:"password"`
	TenantID  string `json:"tenantId"`
	TimeoutSec int   `json:"timeoutSec"` // 0 = 默认 10s
}

// Login 登录。
func (b *SessionBinding) Login(req LoginRequestDTO) (SessionInfoDTO, error) {
	if b.ctx == nil {
		b.ctx = context.Background()
	}
	info, err := b.svc.Login(b.ctx, req.URL, req.Username, req.Password, req.TenantID, req.TimeoutSec)
	if err != nil {
		return SessionInfoDTO{}, toDTOErr(err)
	}
	return SessionInfoDTO{
		LoggedIn: info.LoggedIn, URL: info.URL, TenantID: info.TenantID,
	}, nil
}

// Logout 注销。
func (b *SessionBinding) Logout() error {
	if b.ctx == nil {
		b.ctx = context.Background()
	}
	// 给一个 1s 超时,避免 long-blocking
	ctx, cancel := context.WithTimeout(b.ctx, time.Second)
	defer cancel()
	return toDTOErr(b.svc.Logout(ctx))
}

// Status 返回当前登录态。
func (b *SessionBinding) Status() SessionInfoDTO {
	if b.ctx == nil {
		b.ctx = context.Background()
	}
	info := b.svc.Status(b.ctx)
	return SessionInfoDTO{
		LoggedIn: info.LoggedIn, URL: info.URL, TenantID: info.TenantID,
	}
}

// SessionInfoDTO 前端可见的会话信息。
type SessionInfoDTO struct {
	LoggedIn bool   `json:"loggedIn"`
	URL      string `json:"url"`
	TenantID string `json:"tenantId"`
}

// toDTOErr 把任意 error 翻译成 DTO 友好的 PublicErrorDTO。
// 业务包 rw.PublicError / session.PublicError 同样形态,这里只解 error 类型。
func toDTOErr(err error) error {
	if err == nil {
		return nil
	}
	if pe, ok := err.(interface{ Error() string }); ok {
		// 简化:把内层错误文本传给前端。详细分类在 binding 内各自处理。
		return &PublicErrorDTO{Message: pe.Error(), Kind: "api"}
	}
	return &PublicErrorDTO{Message: err.Error(), Kind: "api"}
}
