package monitor

import (
	"context"
	"fmt"
	"sync"
	"time"

	tptapi "github.com/yzc/tpt_api"

	"scorehub/internal/team"
)

// envClient 持有单个租户的 cub-data 与 datahub 客户端，带主动预刷与静默重登。
type envClient struct {
	mu   sync.Mutex
	env  *team.Env
	base string

	adminUser string // 全局 admin 账号
	adminPass string

	data *tptapi.Client    // cub-data（读位号值）
	dh   *tptapi.TptClient // datahub（ds-info）
}

// scanData 用本租户账号读全部位号实时值；鉴权失败静默重登重试一次。
func (c *envClient) scanData(ctx context.Context) (map[string]any, error) {
	return c.dataCall(ctx, func(cl *tptapi.Client) (map[string]any, error) {
		return cl.ReadRealtimeValues(ctx, TagNames)
	})
}

// scanDs 用本租户账号查全部数据源，返回匹配目标 URL 的数据源（alive 等取第一个命中）。
func (c *envClient) scanDs(ctx context.Context, wantURL string) (found, alive bool, name, url string, err error) {
	var allDs []tptapi.DsInfo
	err = c.dhCall(ctx, func(tc *tptapi.TptClient) error {
		ds, e := tc.GetAllDsInfo()
		if e != nil {
			return e
		}
		allDs = ds
		return nil
	})
	if err != nil {
		return false, false, "", "", err
	}
	for _, ds := range allDs {
		if ds.DsTarUrl == wantURL {
			return true, ds.Alive, ds.DsName, ds.DsTarUrl, nil
		}
	}
	return false, false, "", "", nil
}

func (c *envClient) dataCall(ctx context.Context, fn func(*tptapi.Client) (map[string]any, error)) (res map[string]any, err error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if err := c.ensureData(ctx); err != nil {
		return nil, err
	}
	res, err = fn(c.data)
	if tptapi.IsAuthError(err) {
		c.data = nil
		if err := c.ensureData(ctx); err != nil {
			return nil, err
		}
		return fn(c.data)
	}
	return res, err
}

func (c *envClient) dhCall(ctx context.Context, fn func(*tptapi.TptClient) error) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if err := c.ensureDh(ctx); err != nil {
		return err
	}
	err := fn(c.dh)
	if tptapi.IsTptAuthError(err) {
		c.dh = nil
		if err := c.ensureDh(ctx); err != nil {
			return err
		}
		return fn(c.dh)
	}
	return err
}

func (c *envClient) ensureData(ctx context.Context) error {
	if c.data != nil && c.data.IsLoggedIn() && !c.data.Expired() {
		return nil
	}
	if c.data == nil {
		c.data = tptapi.NewClient(c.base)
	}
	// 各租户统一用全局 admin 账号登录（config 中各租户自带密码多已失效）。
	return c.data.Login(ctx, c.adminUser, c.adminPass, c.env.TenantID)
}

func (c *envClient) ensureDh(ctx context.Context) error {
	if c.dh != nil && !c.dh.Expired() {
		return nil
	}
	tc, err := tptapi.LoginSubject(c.base, c.adminUser, c.adminPass, c.env.TenantID, 30*time.Second)
	if err != nil {
		return err
	}
	c.dh = tc
	return nil
}

// sortEnvs 返回与队伍信息表相同顺序的全部租户（选手按 zkjs，测试放最后）。
func sortEnvs(cfg *team.Config) []*team.Env {
	return team.OrderedEnvs(cfg)
}

// wantURL 构造该租户数据源的目标 URL。
func wantURL(env *team.Env) string {
	return fmt.Sprintf("opc.tcp://%s:18950", env.IPv4)
}