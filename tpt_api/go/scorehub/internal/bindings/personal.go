package bindings

import (
	"context"

	"scorehub/internal/personal"
)

// PersonalBinding 是个性化管理的 Wails 边界适配器。
type PersonalBinding struct {
	ctx context.Context
	svc *personal.Service
}

func NewPersonalBinding(svc *personal.Service) *PersonalBinding {
	return &PersonalBinding{svc: svc}
}

func (b *PersonalBinding) SetContext(ctx context.Context) {
	b.ctx = ctx
}

func (b *PersonalBinding) background() context.Context {
	ctx := b.ctx
	if ctx == nil {
		ctx = context.Background()
	}
	return ctx
}

// GetPersonalList 返回按序号排列的租户列表（附总分）。
func (b *PersonalBinding) GetPersonalList() ([]personal.Row, error) {
	return b.svc.List(b.background())
}

// GetTenantDetail 返回单个租户的成绩详情。
func (b *PersonalBinding) GetTenantDetail(tenantID string) (*personal.Detail, error) {
	return b.svc.Detail(b.background(), tenantID)
}

// CleanupTenant 清空单个租户的评分数据（前端须先弹确认框）。
func (b *PersonalBinding) CleanupTenant(tenantID string) personal.CleanupResult {
	return b.svc.Cleanup(b.background(), tenantID)
}
