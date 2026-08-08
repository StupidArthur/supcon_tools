package ranking

import (
	"context"

	tptapi "github.com/yzc/tpt_api"

	"scorehub/internal/cubauth"
	"scorehub/internal/team"
)

// Service 负责排行榜数据拉取：调 ranking/all → 解析并关联队伍名。
type Service struct {
	session *cubauth.Session
	names   map[string]string
}

// New 构造排行榜 Service，复用共享登录会话。
func New(cfg *team.Config, session *cubauth.Session) *Service {
	names := make(map[string]string, len(cfg.Environments))
	for _, e := range cfg.Environments {
		names[e.TenantID] = e.Name
	}
	return &Service{session: session, names: names}
}

// Fetch 拉取全部租户成绩排名。
func (s *Service) Fetch(ctx context.Context) ([]Item, error) {
	res, err := s.session.Do(ctx, func(c *tptapi.Client) (map[string]any, error) {
		return c.GetRankingAll(ctx)
	})
	if err != nil {
		return nil, err
	}
	items, err := ParseRanking(res)
	if err != nil {
		return nil, err
	}
	AttachNames(items, s.names)
	return items, nil
}
