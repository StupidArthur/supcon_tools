package batch

import (
	"context"

	tptapi "github.com/yzc/tpt_api"

	"scorehub/internal/cubauth"
)

// Service 提供全局评估配置的查看与更新。
type Service struct {
	session *cubauth.Session
}

func New(session *cubauth.Session) *Service {
	return &Service{session: session}
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
