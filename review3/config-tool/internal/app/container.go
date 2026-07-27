package app

import (
	"context"
	"fmt"
	"log"
	"os"

	"config-tool/internal/bindings"
	"config-tool/internal/config"
	"config-tool/internal/realtime"

	wailsRuntime "github.com/wailsapp/wails/v2/pkg/runtime"
)

type Container struct {
	Lifecycle              *Lifecycle
	ComponentBinding       *bindings.ComponentBinding
	ConfigBinding          *bindings.ConfigBinding
	SystemBinding          *bindings.SystemBinding
	TemplateConfigBinding  *bindings.TemplateConfigBinding
	RealtimeProjectBinding *bindings.RealtimeProjectBinding
	RealtimeRuntimeBinding *bindings.RealtimeRuntimeBinding

	// Service 是常驻 DataFactoryService（todo.md §5.1）。
	Service *bindings.DataFactoryServiceManager

	devMode        bool
	wailsGenMode   bool
	ctx            context.Context
}

// NewContainer 创建容器。不阻塞等待 service，UI 先打开。
//
// devMode 选择规则（todo.md §3.1）：
//   - 生产 EXE 默认 devMode=false，使用 <exe>/DataFactoryService.exe
//   - WAILS_GENERATE=1 模式只生成绑定、不启动服务
func NewContainer() (*Container, error) {
	if os.Getenv("WAILS_GENERATE") == "1" {
		return NewContainerWithMode(true, true)
	}
	return NewContainerWithMode(false, false)
}

// NewContainerWithDevMode 创建容器（兼容旧 API）。
func NewContainerWithDevMode(devMode bool) (*Container, error) {
	return NewContainerWithMode(devMode, false)
}

// NewContainerWithMode 创建容器，不阻塞等 service。
func NewContainerWithMode(devMode bool, wailsGenerateMode bool) (*Container, error) {
	if !wailsGenerateMode {
		if _, err := bindings.EnsureAppWorkspaceDirs(); err != nil {
			return nil, fmt.Errorf("应用工作目录初始化失败: %w", err)
		}
	}

	// 编译器先用 noop，service 就绪后替换
	compiler := &noopCompiler{}

	realtimeDir, err := bindings.ResolveRealtimeProjectsDir()
	if err != nil {
		return nil, err
	}
	storage := realtime.NewProjectStorage(realtimeDir)
	manager := realtime.NewManager(storage, compiler)

	metadata, err := config.LoadComponentMetadata()
	if err != nil {
		return nil, err
	}
	configService := config.NewService()

	componentBinding := bindings.NewComponentBinding(metadata)
	configBinding := bindings.NewConfigBinding(configService)
	systemBinding := bindings.NewSystemBinding()
	templateBinding := bindings.NewTemplateConfigBinding()
	realtimeBinding := bindings.NewRealtimeProjectBinding(manager)

	sessionRoot, err := realtime.ResolveSessionRoot()
	if err != nil {
		return nil, err
	}
	sessionManager := realtime.NewSessionManager(sessionRoot)
	runtimeBinding := bindings.NewRealtimeRuntimeBinding(manager, systemBinding, sessionManager)

	lifecycle := NewLifecycle(componentBinding, configBinding, systemBinding, templateBinding, realtimeBinding, runtimeBinding)

	c := &Container{
		Lifecycle:              lifecycle,
		ComponentBinding:       componentBinding,
		ConfigBinding:          configBinding,
		SystemBinding:          systemBinding,
		TemplateConfigBinding:  templateBinding,
		RealtimeProjectBinding: realtimeBinding,
		RealtimeRuntimeBinding: runtimeBinding,
		Service:                nil,
		devMode:                devMode,
		wailsGenMode:           wailsGenerateMode,
	}
	lifecycle.AttachContainer(c)
	return c, nil
}

// StartServiceAsync 在 goroutine 中异步启动 DataFactoryService，就绪后注入绑
// 定并发射 df:service-ready 事件（frontend 切换主 UI）。
func (c *Container) StartServiceAsync(ctx context.Context) {
	c.ctx = ctx
	if c.wailsGenMode {
		wailsRuntime.EventsEmit(ctx, "df:service-ready", map[string]any{
			"skipped": true,
			"message": "Wails 生成模式，跳过服务启动",
		})
		return
	}

	go func() {
		emit := func(pct int, msg string) {
			wailsRuntime.EventsEmit(ctx, "df:service-progress", map[string]any{
				"percent": pct,
				"message": msg,
			})
		}

		emit(0, "正在启动 DataFactory 服务...")

		service, err := bindings.NewDataFactoryServiceManager(c.devMode)
		if err != nil {
			errMsg := fmt.Sprintf("服务启动失败: %s", err.Error())
			log.Printf("[container] %s", errMsg)
			wailsRuntime.EventsEmit(ctx, "df:service-error", map[string]any{
				"error": errMsg,
			})
			return
		}

		emit(50, "服务已就绪，正在初始化...")

		// 注入服务客户端到各 binding
		c.Service = service
		c.RuntimeBinding().SetServiceEndpoint(service.Host(), service.Port(), service.Token())
		c.RuntimeBinding().SetServiceClient(service.Client())
		c.ProjectBinding().SetServiceClient(service.Client())
		c.SystemBinding.SetServiceClient(service.Client())

		// 替换编译器和 session manager 中的 service client
		compiler := bindings.NewServiceRealtimeCompiler(service.Client())
		c.ProjectBinding().SetCompiler(compiler)

		emit(100, "服务就绪")

		wailsRuntime.EventsEmit(ctx, "df:service-ready", map[string]any{
			"host": service.Host(),
			"port": service.Port(),
		})
	}()
}

// RuntimeBinding 是 RealtimeRuntimeBinding 的简写。
func (c *Container) RuntimeBinding() *bindings.RealtimeRuntimeBinding { return c.RealtimeRuntimeBinding }

// ProjectBinding 是 RealtimeProjectBinding 的简写。
func (c *Container) ProjectBinding() *bindings.RealtimeProjectBinding { return c.RealtimeProjectBinding }

// ShutdownService 优雅停止 DataFactoryService（todo.md §6）。
func (c *Container) ShutdownService() {
	if c.Service == nil {
		return
	}
	_ = c.Service.Stop()
}

// InitService 已废弃：服务在 NewContainerWithDevMode 中自动启动（todo.md §3.3）。
// 保留此方法仅为兼容旧调用，实际为 no-op。
func (c *Container) InitService(devMode bool) error {
	return nil
}

// noopCompiler 不调用任何外部依赖的 compiler。
// 用于 wails generate mode 或服务不可用的场景。
type noopCompiler struct{}

func (n *noopCompiler) Validate(_ context.Context, _ []realtime.CompilerSourceSpec) (realtime.ValidationResult, error) {
	return realtime.ValidationResult{Valid: true}, nil
}

func (n *noopCompiler) Compile(_ context.Context, _ []realtime.CompilerSourceSpec, _ string) (string, error) {
	return "", nil
}
