package app

import (
	"fmt"

	"config-tool/internal/bindings"
	"config-tool/internal/config"
	"config-tool/internal/realtime"
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
	// devMode = true 时使用 python standalone_main.py --service 启动；
	// 生产时使用 <exe>/DataFactoryService.exe。
	Service *bindings.DataFactoryServiceManager
}

// NewContainer 创建容器（生产模式）。
func NewContainer() (*Container, error) {
	return NewContainerWithDevMode(false)
}

// NewContainerWithDevMode 创建容器（todo.md §3.1）。
//
// 内部顺序：
//  1. 确保工作目录（project/ + template/）
//  2. 创建 DataFactoryServiceManager
//  3. 等待 /api/health
//  4. 创建 ServiceRealtimeCompiler
//  5. 创建 realtime manager
//  6. 创建 bindings
//  7. 注入统一服务客户端
//  8. 创建 lifecycle
//
// devMode 控制是否走源码 Python --service（生产模式必须 devMode=false）。
func NewContainerWithDevMode(devMode bool) (*Container, error) {
	// 1. 确保工作目录（todo.md §4.2：失败时不继续启动服务和 UI）
	if _, err := bindings.EnsureAppWorkspaceDirs(); err != nil {
		return nil, fmt.Errorf("应用工作目录初始化失败: %w", err)
	}

	// 2-3. 创建并启动 DataFactoryServiceManager（todo.md §3.1）
	service, err := bindings.NewDataFactoryServiceManager(devMode)
	if err != nil {
		return nil, fmt.Errorf("DataFactoryService 启动失败: %w", err)
	}

	// 4. 创建 ServiceRealtimeCompiler（todo.md §7.1）
	compiler := bindings.NewServiceRealtimeCompiler(service.Client())

	// 5. 创建 realtime manager
	// 注意：storage 仍使用旧路径作为 fallback（兼容旧工程），但新工程走 locations map
	realtimeDir, err := bindings.ResolveRealtimeProjectsDir()
	if err != nil {
		service.Stop()
		return nil, err
	}
	storage := realtime.NewProjectStorage(realtimeDir)
	manager := realtime.NewManager(storage, compiler)

	// 6. 创建 bindings
	metadata, err := config.LoadComponentMetadata()
	if err != nil {
		service.Stop()
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
		service.Stop()
		return nil, err
	}
	sessionManager := realtime.NewSessionManager(sessionRoot)
	runtimeBinding := bindings.NewRealtimeRuntimeBinding(manager, systemBinding, sessionManager)

	// 7. 注入统一服务客户端（todo.md §5.2 / §8 / §9）
	runtimeBinding.SetServiceEndpoint(service.Host(), service.Port(), service.Token())
	runtimeBinding.SetServiceClient(service.Client())
	realtimeBinding.SetServiceClient(service.Client())

	// 8. 创建 lifecycle
	lifecycle := NewLifecycle(componentBinding, configBinding, systemBinding, templateBinding, realtimeBinding, runtimeBinding)

	c := &Container{
		Lifecycle:              lifecycle,
		ComponentBinding:       componentBinding,
		ConfigBinding:          configBinding,
		SystemBinding:          systemBinding,
		TemplateConfigBinding:  templateBinding,
		RealtimeProjectBinding: realtimeBinding,
		RealtimeRuntimeBinding: runtimeBinding,
		Service:                service,
	}
	lifecycle.AttachContainer(c)
	return c, nil
}

// InitService 已废弃：服务在 NewContainerWithDevMode 中自动启动（todo.md §3.3）。
// 保留此方法仅为兼容旧调用，实际为 no-op。
func (c *Container) InitService(devMode bool) error {
	return nil
}

// ShutdownService 优雅停止 DataFactoryService（todo.md §6）。
func (c *Container) ShutdownService() {
	if c.Service == nil {
		return
	}
	_ = c.Service.Stop()
}
