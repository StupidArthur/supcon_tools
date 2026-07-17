package app

import (
	"debug-gui/internal/bindings"
)

type Container struct {
	Lifecycle     *Lifecycle
	DebugBinding  *bindings.DebugBinding
}

func NewContainer() (*Container, error) {
	debugBinding := bindings.NewDebugBinding()
	lifecycle := NewLifecycle(debugBinding)

	return &Container{
		Lifecycle:    lifecycle,
		DebugBinding: debugBinding,
	}, nil
}
