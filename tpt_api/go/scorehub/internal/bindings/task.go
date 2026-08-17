package bindings

import (
	"context"

	"scorehub/internal/task"
)

// TaskBinding 是任务管理（选手租户调度任务统计）的 Wails 边界适配器。
type TaskBinding struct {
	ctx context.Context
	svc *task.Service
}

func NewTaskBinding(svc *task.Service) *TaskBinding {
	return &TaskBinding{svc: svc}
}

func (b *TaskBinding) SetContext(ctx context.Context) {
	b.ctx = ctx
}

func (b *TaskBinding) background() context.Context {
	ctx := b.ctx
	if ctx == nil {
		ctx = context.Background()
	}
	return ctx
}

// GetTeamTaskStats 返回全部选手租户的任务统计（按启用数升序）。
func (b *TaskBinding) GetTeamTaskStats() []task.TeamTaskStats {
	return b.svc.Stats(b.background())
}
