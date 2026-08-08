package bindings

import (
	"context"

	"github.com/wailsapp/wails/v2/pkg/runtime"

	"scorehub/internal/monitor"
)

// MonitorBinding 是数据源监控的 Wails 边界适配器。
type MonitorBinding struct {
	ctx context.Context
	svc *monitor.Service

	stop context.CancelFunc
}

func NewMonitorBinding(svc *monitor.Service) *MonitorBinding {
	return &MonitorBinding{svc: svc}
}

func (b *MonitorBinding) SetContext(ctx context.Context) {
	b.ctx = ctx
	// 应用启动即开始监控全部租户。
	b.startLocked(ctx)
}

// ScanMonitor 扫描测试租户一（数据源存活 + 33 位号质量）。
func (b *MonitorBinding) ScanMonitor() (*monitor.Report, error) {
	ctx := b.ctx
	if ctx == nil {
		ctx = context.Background()
	}
	return b.svc.Scan(ctx)
}

// GetMonitorSnapshot 返回最新一轮监控快照（前端切入 tab5 时立即拉取），无数据返回 null。
func (b *MonitorBinding) GetMonitorSnapshot() (*monitor.Snapshot, error) {
	snap, ok := b.svc.Latest()
	if !ok {
		return nil, nil
	}
	return &snap, nil
}

func (b *MonitorBinding) startLocked(ctx context.Context) {
	if b.stop != nil {
		return
	}
	runCtx, cancel := context.WithCancel(ctx)
	b.stop = cancel
	go b.svc.RunPolling(runCtx, monitor.PollInterval, func(snap monitor.Snapshot) {
		if b.ctx == nil {
			return
		}
		runtime.EventsEmit(b.ctx, "monitor:update", snap)
	})
}

// StartMonitor 开始周期轮询所有租户，每轮完成后通过 monitor:update 事件推送快照。
func (b *MonitorBinding) StartMonitor() {
	ctx := b.ctx
	if ctx == nil {
		ctx = context.Background()
	}
	b.startLocked(ctx)
}

// StopMonitor 停止轮询。
func (b *MonitorBinding) StopMonitor() {
	if b.stop != nil {
		b.stop()
		b.stop = nil
	}
}
