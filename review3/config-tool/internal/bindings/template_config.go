package bindings

import (
	"context"
	"path/filepath"

	"config-tool/internal/config"
)

// TemplateConfigBinding 暴露模板 DSL 的无损加载与白名单保存。
//
// 设计原则：
//   - 不复用 ConfigBinding（现有 CanvasState 路径会丢失 display_args / 注释 / 未知键）。
//   - 入口只做 DTO 适配与错误包装，业务逻辑全部在 config.TemplateService。
//   - 内置模板绝对路径解析由 TemplateService.resolveBuiltinTemplatePath 提供，
//     不依赖当前工作目录、不依赖 basename 匹配。
type TemplateConfigBinding struct {
	ctx     context.Context
	service *config.TemplateService
}

// NewTemplateConfigBinding 构造模板 binding。
func NewTemplateConfigBinding() *TemplateConfigBinding {
	return &TemplateConfigBinding{service: config.NewTemplateService()}
}

// SetContext 由 Wails lifecycle 在启动时注入。
func (b *TemplateConfigBinding) SetContext(ctx context.Context) { b.ctx = ctx }

// LoadBuiltinTemplate 通过绝对路径解析加载内置模板。
func (b *TemplateConfigBinding) LoadBuiltinTemplate() (config.TemplateDocument, error) {
	return b.service.LoadBuiltinTemplate()
}

// LoadTemplate 通过 Wails 暴露给前端。
func (b *TemplateConfigBinding) LoadTemplate(path string) (config.TemplateDocument, error) {
	return b.service.LoadTemplate(path)
}

// SaveTemplate 按白名单写回模板。
func (b *TemplateConfigBinding) SaveTemplate(req config.SaveTemplateRequest) (config.SaveTemplateResult, error) {
	return b.service.SaveTemplate(req)
}

// ValidateTemplateConfig 把校验入口暴露给前端，避免前后端重复定义。
func (b *TemplateConfigBinding) ValidateTemplateConfig(cfg config.TemplateConfig) []config.ValidationIssue {
	return config.ValidateTemplateConfig(cfg)
}

// IsBuiltinTemplate 仅用于前端状态提示。
// 真实覆盖判定在 SaveTemplate 内基于 ExpectedHash + 绝对路径比对完成。
func (b *TemplateConfigBinding) IsBuiltinTemplate(path string) bool {
	if path == "" {
		return false
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return false
	}
	builtin, err := config.ResolveBuiltinTemplatePath()
	if err != nil {
		return false
	}
	return abs == builtin
}
