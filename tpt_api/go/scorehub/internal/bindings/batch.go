package bindings

import (
	"context"

	"scorehub/internal/batch"
)

// BatchBinding 是批量管理（全局评估配置）的 Wails 边界适配器。
type BatchBinding struct {
	ctx context.Context
	svc *batch.Service
}

func NewBatchBinding(svc *batch.Service) *BatchBinding {
	return &BatchBinding{svc: svc}
}

func (b *BatchBinding) SetContext(ctx context.Context) {
	b.ctx = ctx
}

func (b *BatchBinding) background() context.Context {
	ctx := b.ctx
	if ctx == nil {
		ctx = context.Background()
	}
	return ctx
}

// GetEvalConfig 查询全局评估配置。
func (b *BatchBinding) GetEvalConfig() (*batch.EvalConfig, error) {
	return b.svc.Get(b.background())
}

// UpdateEvalConfig 全量更新评估配置（练习/考试工况开关、评估时长、上班时间延迟）。
func (b *BatchBinding) UpdateEvalConfig(pracLoadEnabled, examLoadEnabled, evalDurationMinutes, startWorktimeDelayMinutes int) batch.UpdateResult {
	return b.svc.Update(b.background(), pracLoadEnabled, examLoadEnabled, evalDurationMinutes, startWorktimeDelayMinutes)
}

// ClearAllScores 清空所有选手租户的评分记录（危险操作，前端需二次确认）。
func (b *BatchBinding) ClearAllScores() batch.ClearAllResult {
	return b.svc.ClearAllScores(b.background())
}
