package app

import (
	"context"
)

// ContextReceiver 让 Binding 接收 Wails context。
type ContextReceiver interface {
	SetContext(context.Context)
}

// Lifecycle 管理应用启动和关闭。
type Lifecycle struct {
	receivers []ContextReceiver
}

func NewLifecycle(receivers ...ContextReceiver) *Lifecycle {
	return &Lifecycle{receivers: receivers}
}

func (l *Lifecycle) Startup(ctx context.Context) {
	for _, r := range l.receivers {
		r.SetContext(ctx)
	}
}

func (l *Lifecycle) Shutdown(ctx context.Context) {
	// 轻量工具暂无资源需要清理
}
