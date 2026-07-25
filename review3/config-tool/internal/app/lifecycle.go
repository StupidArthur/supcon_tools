package app

import (
	"context"
	"log"

	"config-tool/internal/bindings"
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
	container *Container
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
		// 不暴露 IsPriorityCleanup 作为公共方法（避免 Wails 绑定）。
		// 改用 type assertion：RealtimeRuntimeBinding 的 Cleanup 必须先于
		// SystemBinding 的 Cleanup（先停归档 → 再停 Python）。
		if _, isRT := r.(*bindings.RealtimeRuntimeBinding); isRT {
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
	// 应用启动时即确保 <exe>/project/ 和 <exe>/template/ 存在。
	// 与用户是否点击"新建工程"无关；即使用户只启动应用、不进行任何操作，
	// 目录也会自动出现（todo.md §3.2）。
	if _, err := bindings.EnsureAppWorkspaceDirs(); err != nil {
		log.Printf("应用工作目录初始化失败: %v", err)
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
	if l.container != nil && l.container.Service != nil {
		log.Println("请求常驻 DataFactoryService 关闭...")
		_ = l.container.Service.Stop()
	}
	if l.cancel != nil {
		l.cancel()
	}
	log.Println("DataFactory 组态工具关闭")
}

// AttachContainer 让 Lifecycle 在 Shutdown 时也能访问 Container（用于停服务）。
func (l *Lifecycle) AttachContainer(c *Container) {
	l.container = c
}
