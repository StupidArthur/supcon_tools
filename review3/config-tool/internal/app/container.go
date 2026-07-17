package app

import (
	"config-tool/internal/bindings"
	"config-tool/internal/config"
)

type Container struct {
	Lifecycle        *Lifecycle
	ComponentBinding *bindings.ComponentBinding
	ConfigBinding    *bindings.ConfigBinding
	SystemBinding    *bindings.SystemBinding
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

	lifecycle := NewLifecycle(componentBinding, configBinding, systemBinding)

	return &Container{
		Lifecycle:        lifecycle,
		ComponentBinding: componentBinding,
		ConfigBinding:    configBinding,
		SystemBinding:    systemBinding,
	}, nil
}
