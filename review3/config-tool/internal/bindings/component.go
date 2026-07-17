package bindings

import (
	"context"

	"config-tool/internal/config"
)

type ComponentBinding struct {
	ctx      context.Context
	metadata []config.ComponentMeta
}

func NewComponentBinding(metadata []config.ComponentMeta) *ComponentBinding {
	return &ComponentBinding{metadata: metadata}
}

func (b *ComponentBinding) SetContext(ctx context.Context) {
	b.ctx = ctx
}

func (b *ComponentBinding) List() []config.ComponentMeta {
	return b.metadata
}
