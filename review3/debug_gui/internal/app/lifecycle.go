package app

import (
	"context"
	"log"
)

type ContextReceiver interface {
	SetContext(context.Context)
}

type Lifecycle struct {
	cancel    context.CancelFunc
	receivers []ContextReceiver
}

func NewLifecycle(receivers ...ContextReceiver) *Lifecycle {
	return &Lifecycle{receivers: receivers}
}

func (l *Lifecycle) Startup(ctx context.Context) {
	rootCtx, cancel := context.WithCancel(ctx)
	l.cancel = cancel
	for _, r := range l.receivers {
		r.SetContext(rootCtx)
	}
	log.Println("DataFactory 调试工具启动")
}

func (l *Lifecycle) Shutdown(ctx context.Context) {
	if l.cancel != nil {
		l.cancel()
	}
	log.Println("DataFactory 调试工具关闭")
}
