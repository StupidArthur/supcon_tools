// Package session 提供登录/登出/登录态查询。
//
// 业务包,不 import Wails;可独立 go test。
// 共享 *tptapi.Service 实例由 internal/app/container.go 创建。
package session

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/yzc/tpt_api"
)

// Info 前端可见的登录态快照。不暴露底层 TptClient。
type Info struct {
	LoggedIn bool   `json:"loggedIn"`
	URL      string `json:"url"`
	TenantID string `json:"tenantId"`
}

// Service 登录态业务服务。
type Service struct {
	mu        sync.RWMutex
	tpt       *tptapi.Service
	subject   tptapi.SubjectUrl
	loggedOut bool
}

// NewService 创建依赖 *tptapi.Service 的会话服务。tpt 共享,不可替换。
func NewService(tpt *tptapi.Service) *Service {
	svc := &Service{tpt: tpt}
	if tpt != nil {
		svc.subject = tpt.Info()
	}
	return svc
}

// Login 登录成功返回 Info。password 仅流转不落日志。
func (s *Service) Login(ctx context.Context, url, user, pass, tenantID string, timeoutSec int) (Info, error) {
	if url == "" || user == "" || pass == "" {
		return Info{}, fmt.Errorf("url/user/password 必填")
	}
	timeout := time.Duration(timeoutSec) * time.Second
	if timeout <= 0 {
		timeout = 10 * time.Second
	}
	subject, err := s.tpt.Login(url, user, pass, tenantID, timeout)
	if err != nil {
		return Info{}, err
	}
	s.mu.Lock()
	s.subject = subject
	s.loggedOut = false
	s.mu.Unlock()
	return Info{LoggedIn: true, URL: subject.BaseURL, TenantID: subject.TenantID}, nil
}

// Logout 注销并阻止 binding 层继续访问底层 client。
func (s *Service) Logout(ctx context.Context) error {
	s.mu.Lock()
	s.subject = tptapi.SubjectUrl{}
	s.loggedOut = true
	s.mu.Unlock()
	// tptapi.Service 仍存凭据并可能自动重登,binding 层 session gate 负责拦截。
	return nil
}

// Status 返回当前登录态。不触发网络请求。
func (s *Service) Status(ctx context.Context) Info {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if s.loggedOut || s.subject.BaseURL == "" {
		return Info{}
	}
	return Info{LoggedIn: true, URL: s.subject.BaseURL, TenantID: s.subject.TenantID}
}

// MarkLoggedInForTest 设置登录态为已登录,不执行网络请求。仅测试用。
func (s *Service) MarkLoggedInForTest(url string) {
	s.mu.Lock()
	s.subject = tptapi.SubjectUrl{BaseURL: url}
	s.loggedOut = false
	s.mu.Unlock()
}

// TptService 返回底层 *tptapi.Service,供 internal/rw 复用同一份登录态。
func (s *Service) TptService() *tptapi.Service {
	return s.tpt
}
