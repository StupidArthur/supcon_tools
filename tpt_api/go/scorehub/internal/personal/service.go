package personal

import (
	"context"

	tptapi "github.com/yzc/tpt_api"

	"scorehub/internal/cubauth"
	"scorehub/internal/ranking"
	"scorehub/internal/team"
)

// Service 提供个性化管理数据：租户列表+总分、单租户成绩详情、清空租户评分数据。
type Service struct {
	cfg     *team.Config
	session *cubauth.Session
	ranking *ranking.Service
}

func New(cfg *team.Config, session *cubauth.Session, rankingSvc *ranking.Service) *Service {
	return &Service{cfg: cfg, session: session, ranking: rankingSvc}
}

// List 返回按序号排列的租户行（附排行榜总分，无成绩为 nil）。
func (s *Service) List(ctx context.Context) ([]Row, error) {
	items, err := s.ranking.Fetch(ctx)
	if err != nil {
		return nil, err
	}
	scores := make(map[string]float64, len(items))
	for _, it := range items {
		scores[it.TenantID] = it.TotalScore
	}
	teams := team.ListTeams(s.cfg)
	rows := make([]Row, 0, len(teams))
	for _, t := range teams {
		row := Row{Seq: t.Seq, Name: t.Name, TenantID: t.TenantID, Username: t.Username}
		if v, ok := scores[t.TenantID]; ok {
			row.TotalScore = &v
		}
		rows = append(rows, row)
	}
	return rows, nil
}

// Detail 查询单个租户的成绩详情。
func (s *Service) Detail(ctx context.Context, tenantID string) (*Detail, error) {
	res, err := s.session.Do(ctx, func(c *tptapi.Client) (map[string]any, error) {
		return c.GetTenantDetail(ctx, tenantID)
	})
	if err != nil {
		return nil, err
	}
	return ParseDetail(res)
}

// Cleanup 清空单个租户的评分数据（破坏性操作，调用方须先向用户确认）。
func (s *Service) Cleanup(ctx context.Context, tenantID string) CleanupResult {
	res, err := s.session.Do(ctx, func(c *tptapi.Client) (map[string]any, error) {
		return c.CleanupTenant(ctx, tenantID)
	})
	if err != nil {
		return CleanupResult{Error: err.Error()}
	}
	return ParseCleanup(res)
}
