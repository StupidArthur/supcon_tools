package bindings

import (
	"context"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"

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

// ApplyRuntimeOverridesRequest 正式运行时写回请求 DTO。
type ApplyRuntimeOverridesRequest struct {
	TargetPath   string             `json:"targetPath"`
	ExpectedHash string             `json:"expectedHash"`
	Overrides    map[string]float64 `json:"overrides"`
	IncludeMV    bool               `json:"includeMV"`
}

// ApplyRuntimeOverridesResult 正式运行时写回结果 DTO。
type ApplyRuntimeOverridesResult struct {
	Path          string   `json:"path"`
	ContentHash   string   `json:"contentHash"`
	AppliedFields []string `json:"appliedFields"`
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

// ApplyRuntimeOverrides 将运行时白名单覆盖写回目标 YAML（不得直接覆盖内置模板）。
func (b *TemplateConfigBinding) ApplyRuntimeOverrides(
	req ApplyRuntimeOverridesRequest,
) (ApplyRuntimeOverridesResult, error) {
	empty := ApplyRuntimeOverridesResult{}
	if strings.TrimSpace(req.TargetPath) == "" {
		return empty, fmt.Errorf("targetPath 不能为空")
	}
	if strings.TrimSpace(req.ExpectedHash) == "" {
		return empty, fmt.Errorf("expectedHash 不能为空")
	}
	if len(req.Overrides) == 0 {
		return empty, fmt.Errorf("overrides 不能为空")
	}

	targetAbs, err := filepath.Abs(req.TargetPath)
	if err != nil {
		return empty, fmt.Errorf("解析 targetPath 失败: %w", err)
	}
	if isBuiltinTemplatePath(targetAbs) {
		return empty, fmt.Errorf("禁止直接覆盖内置模板: %s", targetAbs)
	}

	patches := make([]config.TemplatePatch, 0, len(req.Overrides))
	appliedNames := make([]string, 0, len(req.Overrides))
	for rawKey, value := range req.Overrides {
		if !isFiniteFloat(value) {
			return empty, fmt.Errorf("非有限值: %s", rawKey)
		}
		norm, patchPath, isMV, err := normalizeRuntimeOverrideKey(rawKey)
		if err != nil {
			return empty, err
		}
		if isMV && !req.IncludeMV {
			return empty, fmt.Errorf("IncludeMV=false 时禁止写入 MV（%s）", rawKey)
		}
		patches = append(patches, config.TemplatePatch{Path: patchPath, Value: value})
		appliedNames = append(appliedNames, norm)
	}

	res, err := b.service.SaveTemplate(config.SaveTemplateRequest{
		SourcePath:     targetAbs,
		TargetPath:     targetAbs,
		ExpectedHash:   req.ExpectedHash,
		AllowOverwrite: false,
		Patches:        patches,
	})
	if err != nil {
		return empty, err
	}
	return ApplyRuntimeOverridesResult{
		Path:          res.NewPath,
		ContentHash:   res.NewHash,
		AppliedFields: appliedNames,
	}, nil
}

func isFiniteFloat(v float64) bool {
	return !math.IsNaN(v) && !math.IsInf(v, 0)
}

func isBuiltinTemplatePath(targetAbs string) bool {
	targetAbs = filepath.Clean(targetAbs)
	if builtinAbs, err := config.ResolveBuiltinTemplatePath(); err == nil && builtinAbs != "" {
		return samePathOrFile(targetAbs, builtinAbs)
	}
	// ResolveBuiltin may fail under `go test` (exe in build cache). Discover the
	// real builtin by walking ancestors: Join(ancestor, "config/单阀门二阶水箱.yaml")
	// compared via Clean / EqualFold / SameFile — never basename-only.
	// Copies named the same under other folders (e.g. tmp/验收/…) stay writable.
	dir := filepath.Dir(targetAbs)
	for i := 0; i < 8; i++ {
		candidate := filepath.Clean(filepath.Join(dir, config.BuiltinTemplateRelativePath))
		if samePathOrFile(targetAbs, candidate) {
			return true
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return false
}

func samePathOrFile(a, b string) bool {
	ca := filepath.Clean(a)
	cb := filepath.Clean(b)
	if strings.EqualFold(ca, cb) {
		return true
	}
	fa, errA := os.Stat(ca)
	fb, errB := os.Stat(cb)
	if errA != nil || errB != nil {
		return false
	}
	return os.SameFile(fa, fb)
}

// normalizeRuntimeOverrideKey maps runtime tags to TemplatePatch paths.
// Returns (canonicalAppliedName, patchPath, isMV, error).
func normalizeRuntimeOverrideKey(raw string) (string, string, bool, error) {
	key := strings.TrimSpace(raw)
	upper := strings.ToUpper(key)
	switch upper {
	case "PV", "TANK_2.LEVEL", "TANK_1.LEVEL", "VALVE_1.CURRENT_OPENING",
		"SOURCE_FLOW", "AUTO", "CAS":
		return "", "", false, fmt.Errorf("禁止写回字段: %s", raw)
	}

	attr := key
	if strings.Contains(key, ".") {
		parts := strings.Split(key, ".")
		attr = parts[len(parts)-1]
	}
	attrU := strings.ToUpper(attr)
	switch attrU {
	case "SV":
		return "pid2.SV", "pid.SV", false, nil
	case "PB":
		return "pid2.PB", "pid.PB", false, nil
	case "TI":
		return "pid2.TI", "pid.TI", false, nil
	case "TD":
		return "pid2.TD", "pid.TD", false, nil
	case "KD":
		return "pid2.KD", "pid.KD", false, nil
	case "MV":
		return "pid2.MV", "pid.MV", true, nil
	case "PV", "LEVEL", "CURRENT_OPENING", "AUTO", "CAS":
		return "", "", false, fmt.Errorf("禁止写回字段: %s", raw)
	default:
		return "", "", false, fmt.Errorf("未知或非白名单字段: %s", raw)
	}
}
