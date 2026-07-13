package app

import (
	"context"
	"sync"
)

// Lifecycle 持有应用根 context + Binding 的 context 注入。
//
// 本工具不后台长任务、不启 Worker、不开本地端口,所以这里只是 Lifecycle 的轻量实现,
// 留作以后扩展位(参见 dev-skill gui-tool/wails-backend.md §五)。
type Lifecycle struct {
	mu       sync.Mutex
	cancel   context.CancelFunc
	receivers []ContextReceiver
}

// ContextReceiver 让 binding 拿到应用根 context。
// 满足此接口的 binding 在 Startup 中通过 SetContext 注入。
type ContextReceiver interface {
	SetContext(context.Context)
}

// NewLifecycle 创建 Lifecycle。
func NewLifecycle() *Lifecycle {
	return &Lifecycle{}
}

// Startup Wails 启动钩子。构造应用根 context,推给所有 binding。
func (l *Lifecycle) Startup(ctx context.Context) {
	rootCtx, cancel := context.WithCancel(ctx)
	l.mu.Lock()
	l.cancel = cancel
	receivers := l.receivers
	l.mu.Unlock()

	for _, r := range receivers {
		r.SetContext(rootCtx)
	}
}

// Shutdown Wails 关闭钩子。取消根 context,清理资源。
func (l *Lifecycle) Shutdown(_ context.Context) {
	l.mu.Lock()
	cancel := l.cancel
	l.mu.Unlock()
	if cancel != nil {
		cancel()
	}
}

// Register 注册一个 ContextReceiver。仅在 Container 构造后由 binding 回调一次。
func (l *Lifecycle) Register(r ContextReceiver) {
	l.mu.Lock()
	l.receivers = append(l.receivers, r)
	l.mu.Unlock()
}
