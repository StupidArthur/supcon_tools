package bindings

import (
	"context"

	"scorehub/internal/team"
)

// TeamBinding 是队伍信息的 Wails 边界适配器。
type TeamBinding struct {
	ctx context.Context
	cfg *team.Config
}

func NewTeamBinding(cfg *team.Config) *TeamBinding {
	return &TeamBinding{cfg: cfg}
}

func (b *TeamBinding) SetContext(ctx context.Context) {
	b.ctx = ctx
}

// GetTeams 返回排序后的租户列表。
func (b *TeamBinding) GetTeams() ([]team.Team, error) {
	cfg := b.cfg
	if cfg == nil {
		var err error
		cfg, err = team.LoadConfig()
		if err != nil {
			return nil, err
		}
	}
	return team.ListTeams(cfg), nil
}
