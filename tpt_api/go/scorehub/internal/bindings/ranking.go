package bindings

import (
	"context"

	"scorehub/internal/ranking"
)

// RankingBinding 是排行榜的 Wails 边界适配器。
type RankingBinding struct {
	ctx context.Context
	svc *ranking.Service
}

func NewRankingBinding(svc *ranking.Service) *RankingBinding {
	return &RankingBinding{svc: svc}
}

func (b *RankingBinding) SetContext(ctx context.Context) {
	b.ctx = ctx
}

// GetRanking 返回所有租户成绩排名列表。
func (b *RankingBinding) GetRanking() ([]ranking.Item, error) {
	ctx := b.ctx
	if ctx == nil {
		ctx = context.Background()
	}
	return b.svc.Fetch(ctx)
}
