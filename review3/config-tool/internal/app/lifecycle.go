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

type Lifecycle struct {
	cancel    context.CancelFunc
	receivers []ContextReceiver
	cleanups  []CleanupReceiver
}

func NewLifecycle(receivers ...ContextReceiver) *Lifecycle {
	l := &Lifecycle{receivers: receivers}
	// 收集需要 Cleanup 的 receiver
	for _, r := range receivers {
		if c, ok := r.(CleanupReceiver); ok {
			l.cleanups = append(l.cleanups, c)
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
	// 清理子进程
	for _, c := range l.cleanups {
		c.Cleanup()
	}
	if l.cancel != nil {
		l.cancel()
	}
	log.Println("DataFactory 组态工具关闭")
}
