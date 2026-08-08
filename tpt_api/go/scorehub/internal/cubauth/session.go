package cubauth

import (
	"context"
	"fmt"
	"sync"
	"time"

	tptapi "github.com/yzc/tpt_api"

	"scorehub/internal/team"
)

// Session 是共享的 TPT 登录会话（测试租户一账号），供各域 Service 复用。
//
// 鉴权策略：token 临近过期（Client.Expired()/TptClient.Expired()，预留 5 分钟缓冲）
// 提前主动重登，避免轮询中途遭鉴权错误；若仍触发鉴权错误，则静默重登重试一次，
// 那次失败不进日志、不影响本周期数据（重登后重新拿到数据）。
type Session struct {
	baseURL  string
	username string
	password string
	tenantID string

	mu       sync.Mutex
	client   *tptapi.Client    // cub-data 域（读位号值）
	dhClient *tptapi.TptClient // datahub 域（ds-info）
}

// PickAuthEnv 选出共享鉴权使用的租户：第一个"测试"类型租户（即测试租户一）。
func PickAuthEnv(cfg *team.Config) (*team.Env, error) {
	for i := range cfg.Environments {
		if cfg.Environments[i].Type == "测试" {
			return &cfg.Environments[i], nil
		}
	}
	return nil, fmt.Errorf("config: no test tenant found")
}

// NewSession 从全局配置构造会话，鉴权账号取第一个"测试"类型租户（即测试租户一）。
func NewSession(cfg *team.Config) (*Session, error) {
	env, err := PickAuthEnv(cfg)
	if err != nil {
		return nil, err
	}
	return &Session{
		baseURL:  cfg.BaseURL,
		username: env.Username,
		password: env.Password,
		tenantID: env.TenantID,
	}, nil
}

// Do 在已登录的 cub-data 客户端上执行业务调用；未登录自动登录，token 临近过期自动预刷，
// 鉴权失败静默重登重试一次（失败不进日志，重试后重新拿到数据）。
func (s *Session) Do(ctx context.Context, fn func(*tptapi.Client) (map[string]any, error)) (map[string]any, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if err := s.ensureClientLogin(ctx); err != nil {
		return nil, err
	}
	res, err := fn(s.client)
	if tptapi.IsAuthError(err) {
		s.client.Logout()
		if err := s.ensureClientLogin(ctx); err != nil {
			return nil, err
		}
		return fn(s.client)
	}
	return res, err
}

// DoDatahub 在已登录的 datahub 客户端上执行业务调用；过期自动预刷，鉴权失败静默重登重试一次。
func (s *Session) DoDatahub(ctx context.Context, fn func(*tptapi.TptClient) error) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if err := s.ensureDatahubLogin(ctx); err != nil {
		return err
	}
	err := fn(s.dhClient)
	if tptapi.IsTptAuthError(err) {
		s.dhClient = nil
		if err := s.ensureDatahubLogin(ctx); err != nil {
			return err
		}
		return fn(s.dhClient)
	}
	return err
}

func (s *Session) ensureClientLogin(ctx context.Context) error {
	if s.client != nil && s.client.IsLoggedIn() && !s.client.Expired() {
		return nil
	}
	if s.client == nil {
		s.client = tptapi.NewClient(s.baseURL)
	}
	return s.client.Login(ctx, s.username, s.password, s.tenantID)
}

func (s *Session) ensureDatahubLogin(ctx context.Context) error {
	if s.dhClient != nil && !s.dhClient.Expired() {
		return nil
	}
	tc, err := tptapi.LoginSubject(s.baseURL, s.username, s.password, s.tenantID, 30*time.Second)
	if err != nil {
		return err
	}
	s.dhClient = tc
	return nil
}