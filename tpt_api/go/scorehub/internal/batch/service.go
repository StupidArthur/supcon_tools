package batch

import (
	"context"

	tptapi "github.com/yzc/tpt_api"

	"scorehub/internal/cubauth"
	"scorehub/internal/team"
)

// Service 提供全局评估配置的查看与更新，以及批量清空选手评分记录。
type Service struct {
	cfg     *team.Config
	session *cubauth.Session
}

func New(cfg *team.Config, session *cubauth.Session) *Service {
	return &Service{cfg: cfg, session: session}
}

// Get 查询全局评估配置（不存在时服务端自动初始化默认配置）。
func (s *Service) Get(ctx context.Context) (*EvalConfig, error) {
	res, err := s.session.Do(ctx, func(c *tptapi.Client) (map[string]any, error) {
		return c.GetEvalConfig(ctx)
	})
	if err != nil {
		return nil, err
	}
	return ParseEvalConfig(res)
}

// Update 全量更新四个可改字段（练习/考试工况开关、评估时长、上班时间延迟）。
func (s *Service) Update(ctx context.Context, pracLoadEnabled, examLoadEnabled, evalDurationMinutes, startWorktimeDelayMinutes int) UpdateResult {
	res, err := s.session.Do(ctx, func(c *tptapi.Client) (map[string]any, error) {
		return c.UpdateEvalConfig(ctx, &pracLoadEnabled, &examLoadEnabled, &evalDurationMinutes, &startWorktimeDelayMinutes)
	})
	if err != nil {
		return UpdateResult{Error: err.Error()}
	}
	return ParseUpdate(res)
}

// ClearAllScores 遍历所有选手租户，逐个用全局 admin 账号登录后清空其评分记录。
// 测试租户跳过。返回每个租户的逐一结果与成功/失败计数。
func (s *Service) ClearAllScores(ctx context.Context) ClearAllResult {
	var out ClearAllResult
	envs := team.OrderedEnvs(s.cfg)
	for _, env := range envs {
		if env.Type == "测试" {
			continue
		}
		item := TenantClearResult{Seq: len(out.Items) + 1, Name: env.Name, TenantID: env.TenantID}
		if err := s.clearOne(ctx, env); err != nil {
			item.Error = err.Error()
			out.Failed++
		} else {
			item.Success = true
			out.Success++
		}
		out.Items = append(out.Items, item)
	}
	return out
}

// clearOne 用全局 admin 账号登录指定租户并清空其评分记录。
func (s *Service) clearOne(ctx context.Context, env *team.Env) error {
	c := tptapi.NewClient(s.cfg.BaseURL)
	if err := c.Login(ctx, s.cfg.Admin.Username, s.cfg.Admin.Password, env.TenantID); err != nil {
		return err
	}
	defer c.Logout()
	res, err := c.ClearMyRecords(ctx)
	if err != nil {
		return err
	}
	return checkClear(res)
}

// checkClear 检查清空接口返回的 code 是否为 200。
func checkClear(res map[string]any) error {
	code, _ := res["code"].(float64)
	if code != 200 {
		msg, _ := res["message"].(string)
		return &ClearError{Code: res["code"], Message: msg}
	}
	return nil
}
