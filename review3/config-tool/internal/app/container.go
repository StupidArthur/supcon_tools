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
}

func NewContainer() (*Container, error) {
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

	lifecycle := NewLifecycle(componentBinding, configBinding, systemBinding, templateBinding, realtimeBinding)

	return &Container{
		Lifecycle:              lifecycle,
		ComponentBinding:       componentBinding,
		ConfigBinding:          configBinding,
		SystemBinding:          systemBinding,
		TemplateConfigBinding:  templateBinding,
		RealtimeProjectBinding: realtimeBinding,
	}, nil
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

