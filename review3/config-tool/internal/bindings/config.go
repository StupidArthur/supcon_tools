package bindings

import (
	"context"

	"config-tool/internal/config"
)

type ConfigBinding struct {
	ctx     context.Context
	service *config.Service
}

func NewConfigBinding(service *config.Service) *ConfigBinding {
	return &ConfigBinding{service: service}
}

func (b *ConfigBinding) SetContext(ctx context.Context) {
	b.ctx = ctx
}

func (b *ConfigBinding) ExportYAML(canvas config.CanvasState, path string) error {
	return b.service.ExportYAML(canvas, path)
}

func (b *ConfigBinding) ImportYAML(path string) (config.CanvasState, error) {
	return b.service.ImportYAML(path)
}

func (b *ConfigBinding) Validate(canvas config.CanvasState) (config.ValidationResult, error) {
	return b.service.Validate(canvas)
}

func (b *ConfigBinding) SaveCanvas(canvas config.CanvasState, path string) error {
	return b.service.SaveCanvas(canvas, path)
}

func (b *ConfigBinding) LoadCanvas(path string) (config.CanvasState, error) {
	return b.service.LoadCanvas(path)
}
