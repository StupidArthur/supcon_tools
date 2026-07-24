package app

import (
	"context"
	"log"
)

type ContextReceiver interface {
	SetContext(context.Context)
}

type CleanupReceiver interface {
	Cleanup()
}

// PriorityCleanupReceiver：标记一个 receiver 的 Cleanup 必须在普通 cleanup 之前
// 运行。用于让 RealtimeRuntimeBinding 先于 SystemBinding 执行清理，
// 保证归档停止（带 Bearer 鉴权）在 Python 进程被终止前完成。
type PriorityCleanupReceiver interface {
	CleanupReceiver
	IsPriorityCleanup() bool
}

type Lifecycle struct {
	cancel    context.CancelFunc
	receivers []ContextReceiver
	// cleanups 分两段：priority 先于 normal，保证依赖顺序。
	priorityCleanups []CleanupReceiver
	normalCleanups   []CleanupReceiver
}

func NewLifecycle(receivers ...ContextReceiver) *Lifecycle {
	l := &Lifecycle{receivers: receivers}
	for _, r := range receivers {
		c, ok := r.(CleanupReceiver)
		if !ok {
			continue
		}
		if p, ok := r.(PriorityCleanupReceiver); ok && p.IsPriorityCleanup() {
			l.priorityCleanups = append(l.priorityCleanups, c)
		} else {
			l.normalCleanups = append(l.normalCleanups, c)
		}
	}
	return l
}

func (l *Lifecycle) Startup(ctx context.Context) {
	rootCtx, cancel := context.WithCancel(ctx)
	l.cancel = cancel
	for _, r := range l.receivers {
		r.SetContext(rootCtx)
	}
	log.Println("DataFactory 组态工具启动")
}

func (l *Lifecycle) Shutdown(ctx context.Context) {
	// 关键：先 priority（RealtimeRuntimeBinding.Cleanup → 归档 stop + Python stop），
	// 再 normal（SystemBinding.Cleanup 此时 b.proc 已被清空，是 no-op）。
	// 旧顺序：normal 先（SystemBinding.Cleanup 直接 Kill Python），
	// 导致 RealtimeRuntimeBinding 看不到 Python，archive stop 请求失败。
	for _, c := range l.priorityCleanups {
		c.Cleanup()
	}
	for _, c := range l.normalCleanups {
		c.Cleanup()
	}
	if l.cancel != nil {
		l.cancel()
	}
	log.Println("DataFactory 组态工具关闭")
}
