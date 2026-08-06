package app

import (
	"scorehub/internal/bindings"
)

// Container 是唯一组合根，创建所有依赖。
type Container struct {
	Lifecycle    *Lifecycle
	TeamBinding  *bindings.TeamBinding
}

func NewContainer() (*Container, error) {
	teamBinding := bindings.NewTeamBinding()

	lifecycle := NewLifecycle(teamBinding)

	return &Container{
		Lifecycle:   lifecycle,
		TeamBinding: teamBinding,
	}, nil
}
