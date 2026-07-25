package app

import (
	"context"
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

	// Service 是常驻 DataFactoryService（todo.md §7）。
	// devMode = true 时使用 python standalone_main.py --service 启动；
	// 生产时使用 <exe>/DataFactoryService.exe。
	Service *bindings.DataFactoryServiceManager
}

func NewContainer() (*Container, error) {
	return NewContainerWithDevMode(false)
}

// NewContainerWithDevMode 创建容器；devMode 决定是否走 Python --service。
// 生产模式 devMode=false；开发调试时 devMode=true。
func NewContainerWithDevMode(devMode bool) (*Container, error) {
	metadata, err := config.LoadComponentMetadata()
	if err != nil {
		return nil, err
	}

	configService := config.NewService()

	componentBinding := bindings.NewComponentBinding(metadata)
	configBinding := bindings.NewConfigBinding(configService)
	systemBinding := bindings.NewSystemBinding()
	templateBinding := bindings.NewTemplateConfigBinding()

	realtimeDir, err := bindings.ResolveRealtimeProjectsDir()
	if err != nil {
		return nil, err
	}
	storage := realtime.NewProjectStorage(realtimeDir)
	compiler := resolveRealtimeCompiler()
	manager := realtime.NewManager(storage, compiler)
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
	}
	lifecycle.AttachContainer(c)
	return c, nil
}

func resolveRealtimeCompiler() realtime.RealtimeCompiler {
	launch, err := bindings.ResolveDataFactoryLaunchPublic()
	if err != nil {
		return &noopCompiler{}
	}
	return realtime.NewPythonRealtimeCompiler(launch.Exe, launch.PrefixArgs, launch.WorkDir)
}

type noopCompiler struct{}

func (n *noopCompiler) Validate(_ context.Context, _ []realtime.CompilerSourceSpec) (realtime.ValidationResult, error) {
	return realtime.ValidationResult{Valid: true, Instances: []realtime.ExpandedInstance{}, Duplicates: []realtime.DuplicateInstance{}}, nil
}

func (n *noopCompiler) Compile(_ context.Context, _ []realtime.CompilerSourceSpec, _ string) (string, error) {
	return "", fmt.Errorf("DataFactory 未找到，无法编译工程")
}

// InitService 启动常驻 DataFactoryService（todo.md §7.5）。
// devMode 控制是否走源码 Python --service（生产模式必须 devMode=false）。
func (c *Container) InitService(devMode bool) error {
	if c.Service != nil {
		return nil
	}
	svc, err := bindings.NewDataFactoryServiceManager(devMode)
	if err != nil {
		return err
	}
	c.Service = svc
	// 注入服务端口 + Token 给 RealtimeRuntimeBinding 用于 API 连接
	c.RealtimeRuntimeBinding.SetServiceEndpoint(svc.Host(), svc.Port(), svc.Token())
	return nil
}

// ShutdownService 优雅停止 DataFactoryService（todo.md §7.5）。
func (c *Container) ShutdownService() {
	if c.Service == nil {
		return
	}
	_ = c.Service.Stop()
}

