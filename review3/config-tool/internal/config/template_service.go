package config

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"
)

// TemplateService 实现模板 DSL 的无损加载与白名单保存。
//
// 设计原则：
//   - 直接基于 yaml.v3.Node 操作，保留 display_args、未知键、注释和 program 顺序。
//   - 所有数值写入只走白名单路径；非白名单字段在 Save 时绝不改动。
//   - 写盘仅触碰被本次请求的 patches 命中的叶子，绝不重写其他白名单字段；
//     也绝不主动为缺失字段补默认键（缺失字段由 Python 组件 default_params 兜底）。
//   - pid.PV 是运行时只读值，绝不参与白名单写入。
//   - 内置模板默认不可静默覆盖；保存请求必须显式 AllowOverwrite=true 才能写回原路径。
//   - ExpectedHash 不允许为空，避免外部修改被无感覆盖。
//   - 写盘使用 临时文件 + 原子 rename 的模式，失败时不破坏原始文件。
type TemplateService struct{}

// NewTemplateService 构造一个无状态的模板服务实例。
func NewTemplateService() *TemplateService { return &TemplateService{} }

// 固定拓扑：阶段 1 模板必须包含这 5 个 program 且 name/type/inputs/execute_first 匹配。
// name 区分大小写；type 的大小写在比对前会做 ToUpper。
var fixedTopology = []struct {
	name         string
	typeStr      string
	inputs       map[string]string
	executeFirst bool
}{
	{name: "source_flow", typeStr: "Variable"},
	{
		name:    "valve_1",
		typeStr: "VALVE",
		inputs: map[string]string{
			"target_opening": "pid2.MV",
			"inlet_flow":     "source_flow",
		},
	},
	{
		name:    "tank_1",
		typeStr: "CYLINDRICAL_TANK",
		inputs: map[string]string{
			"inlet_flow": "valve_1.outlet_flow",
		},
	},
	{
		name:    "tank_2",
		typeStr: "CYLINDRICAL_TANK",
		inputs: map[string]string{
			"inlet_flow": "tank_1.outlet_flow",
		},
	},
	{
		name:         "pid2",
		typeStr:      "PID",
		executeFirst: true,
		inputs: map[string]string{
			"PV": "tank_2.level",
		},
	},
}

// pythonValveDefaults 来自 components/programs/valve.py 的 VALVE.default_params。
// 当 YAML 中相应字段缺失时，使用这些默认值填入 cfg，使得 UI 显示与 Python
// 运行时一致；但写盘时仍以 modifiedPaths 控制是否真正写入。
var pythonValveDefaults = ValveConfig{
	MinOpening:      0.0,
	MaxOpening:      100.0,
	FullTravelTime:  10.0,
	InitialOpening:  0.0,
	FlowCoefficient: 1.0,
}

// resolveBuiltinTemplatePath 按以下顺序定位内置模板的绝对路径：
//  1. 环境变量 SUPCON_TOOL_REPO_ROOT（测试和 CI 优先使用）
//  2. 从 os.Executable() 所在目录向上最多 8 层查找 config/单阀门二阶水箱.yaml
//
// 一律返回绝对路径，不依赖当前工作目录，也不依赖 basename 匹配。
func ResolveBuiltinTemplatePath() (string, error) {
	if root := strings.TrimSpace(os.Getenv("SUPCON_TOOL_REPO_ROOT")); root != "" {
		abs, _ := filepath.Abs(root)
		candidate := filepath.Join(abs, BuiltinTemplateRelativePath)
		if _, err := os.Stat(candidate); err == nil {
			return candidate, nil
		}
		return "", fmt.Errorf("SUPCON_TOOL_REPO_ROOT=%q 不包含 %s", abs, BuiltinTemplateRelativePath)
	}
	exe, err := os.Executable()
	if err != nil {
		return "", fmt.Errorf("获取可执行文件路径失败: %w", err)
	}
	return resolveBuiltinTemplatePathFrom(filepath.Dir(exe))
}

// resolveBuiltinTemplatePathFrom is the testable executable-layout branch of
// ResolveBuiltinTemplatePath. startDir is normally filepath.Dir(os.Executable()).
func resolveBuiltinTemplatePathFrom(startDir string) (string, error) {
	dir, err := filepath.Abs(startDir)
	if err != nil {
		return "", fmt.Errorf("解析可执行文件目录失败: %w", err)
	}
	for i := 0; i < 8; i++ {
		candidate := filepath.Join(dir, BuiltinTemplateRelativePath)
		if _, err := os.Stat(candidate); err == nil {
			abs, _ := filepath.Abs(candidate)
			return abs, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return "", fmt.Errorf("无法定位内置模板 %s；请设置 SUPCON_TOOL_REPO_ROOT", BuiltinTemplateRelativePath)
}

// LoadBuiltinTemplate 解析内置模板并返回 TemplateDocument。
// 若 SUPCON_TOOL_REPO_ROOT 未设置且无法从可执行文件向上定位，则返回错误。
func (s *TemplateService) LoadBuiltinTemplate() (TemplateDocument, error) {
	path, err := ResolveBuiltinTemplatePath()
	if err != nil {
		return TemplateDocument{}, err
	}
	return s.LoadTemplate(path)
}

// LoadTemplate 从 path 读取模板并返回无损文档。
func (s *TemplateService) LoadTemplate(path string) (TemplateDocument, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return TemplateDocument{}, fmt.Errorf("解析路径失败: %w", err)
	}

	raw, err := os.ReadFile(abs)
	if err != nil {
		return TemplateDocument{}, fmt.Errorf("读取文件失败: %w", err)
	}

	node := &yaml.Node{}
	if err := yaml.Unmarshal(raw, node); err != nil {
		return TemplateDocument{}, fmt.Errorf("解析 YAML 失败: %w", err)
	}

	doc, err := s.materialize(abs, raw, node)
	if err != nil {
		return TemplateDocument{}, err
	}
	return doc, nil
}

// SaveTemplate 按白名单 patches 写回 target path。
//
// 强制约束：
//   - ExpectedHash 必须非空；
//   - 当 target 解析后与 source 解析后相同时，必须满足 ExpectedHash == 磁盘当前 hash；
//   - 当 target != source 且 target 文件已存在时，必须 AllowOverwrite=true；
//   - target 为内置模板时必须 AllowOverwrite=true（无论 source 与 target 是否相同）；
//   - 写盘只修改被本次请求的 patches 实际改变数值的字段；
//   - 写盘后必须通过 ValidateTemplateConfig 才算成功。
func (s *TemplateService) SaveTemplate(req SaveTemplateRequest) (SaveTemplateResult, error) {
	if req.SourcePath == "" || req.TargetPath == "" {
		return SaveTemplateResult{}, fmt.Errorf("sourcePath/targetPath 不能为空")
	}
	if strings.TrimSpace(req.ExpectedHash) == "" {
		return SaveTemplateResult{}, errors.New("expectedHash 不能为空")
	}

	srcAbs, err := filepath.Abs(req.SourcePath)
	if err != nil {
		return SaveTemplateResult{}, fmt.Errorf("解析 sourcePath 失败: %w", err)
	}
	tgtAbs, err := filepath.Abs(req.TargetPath)
	if err != nil {
		return SaveTemplateResult{}, fmt.Errorf("解析 targetPath 失败: %w", err)
	}

	raw, err := os.ReadFile(srcAbs)
	if err != nil {
		return SaveTemplateResult{}, fmt.Errorf("读取源文件失败: %w", err)
	}
	currentHash := hashBytes(raw)
	if req.ExpectedHash != currentHash {
		return SaveTemplateResult{}, fmt.Errorf("磁盘哈希已变更 (expected=%s actual=%s)：请重新加载后再保存",
			shortHash(req.ExpectedHash), shortHash(currentHash))
	}

	// 覆盖策略：target 与 source 同路径时上面 hash 检查已覆盖；
	// 不同路径时若 target 已存在，必须显式 allowOverwrite。
	if srcAbs != tgtAbs {
		if _, statErr := os.Stat(tgtAbs); statErr == nil && !req.AllowOverwrite {
			return SaveTemplateResult{}, fmt.Errorf("目标文件已存在 %s：覆盖需显式确认 (allowOverwrite=true)", tgtAbs)
		}
	}
	// 内置模板：无论是否与 source 同路径，都必须显式 allowOverwrite。
	builtinAbs, _ := ResolveBuiltinTemplatePath()
	if builtinAbs != "" && tgtAbs == builtinAbs && !req.AllowOverwrite {
		return SaveTemplateResult{}, fmt.Errorf("内置模板 %s 默认禁止覆盖，请显式确认 (allowOverwrite=true) 或另存为新文件",
			BuiltinTemplateRelativePath)
	}

	node := &yaml.Node{}
	if err := yaml.Unmarshal(raw, node); err != nil {
		return SaveTemplateResult{}, fmt.Errorf("解析源 YAML 失败: %w", err)
	}

	doc, err := s.materialize(srcAbs, raw, node)
	if err != nil {
		return SaveTemplateResult{}, err
	}

	// 应用白名单 patch，返回最终 cfg 与本次实际修改的路径集合。
	cfg, modifiedPaths, err := applyPatchesToConfig(doc.Config, req.Patches)
	if err != nil {
		return SaveTemplateResult{}, err
	}

	// 写盘阶段：只修改 modifiedPaths 中的叶子。
	if err := writeConfigIntoNode(node, cfg, modifiedPaths); err != nil {
		return SaveTemplateResult{}, err
	}

	// 整批校验：NaN/Inf、范围、跨字段约束（包括不可达流量与 Tank 1 溢流）。
	if errs := ValidateTemplateConfig(cfg); len(errs) > 0 {
		return SaveTemplateResult{}, &ValidationError{Issues: errs}
	}

	if err := os.MkdirAll(filepath.Dir(tgtAbs), 0o755); err != nil {
		return SaveTemplateResult{}, fmt.Errorf("创建目录失败: %w", err)
	}

	tmp, err := os.CreateTemp(filepath.Dir(tgtAbs), ".template-*.yaml")
	if err != nil {
		return SaveTemplateResult{}, fmt.Errorf("创建临时文件失败: %w", err)
	}
	tmpPath := tmp.Name()
	defer func() {
		if _, statErr := os.Stat(tmpPath); statErr == nil {
			_ = os.Remove(tmpPath)
		}
	}()

	enc := yaml.NewEncoder(tmp)
	enc.SetIndent(2)
	if err := enc.Encode(node); err != nil {
		tmp.Close()
		return SaveTemplateResult{}, fmt.Errorf("编码 YAML 失败: %w", err)
	}
	if err := enc.Close(); err != nil {
		tmp.Close()
		return SaveTemplateResult{}, fmt.Errorf("关闭 encoder 失败: %w", err)
	}
	if _, err := tmp.Write([]byte("\n")); err != nil {
		tmp.Close()
		return SaveTemplateResult{}, fmt.Errorf("写换行失败: %w", err)
	}
	if err := tmp.Close(); err != nil {
		return SaveTemplateResult{}, fmt.Errorf("关闭临时文件失败: %w", err)
	}

	if err := os.Rename(tmpPath, tgtAbs); err != nil {
		return SaveTemplateResult{}, fmt.Errorf("替换目标文件失败: %w", err)
	}

	// 重新加载最终落盘结果，得到最新的 hash 与 document。
	final, err := s.LoadTemplate(tgtAbs)
	if err != nil {
		return SaveTemplateResult{}, fmt.Errorf("保存后重新加载失败: %w", err)
	}

	return SaveTemplateResult{
		NewPath:     tgtAbs,
		NewHash:     final.ContentHash,
		NewDocument: final,
	}, nil
}

// ValidationError 把多条校验问题打包成单个错误。
// 调用方可通过 errors.As 取回全部 issues。
type ValidationError struct {
	Issues []ValidationIssue
}

func (e *ValidationError) Error() string {
	if len(e.Issues) == 0 {
		return "配置校验失败"
	}
	msgs := make([]string, 0, len(e.Issues))
	for _, it := range e.Issues {
		msgs = append(msgs, fmt.Sprintf("[%s] %s: %s", it.Level, it.Path, it.Message))
	}
	return "配置校验失败: " + strings.Join(msgs, "; ")
}

// ValidateTemplateConfig 是白名单写入后的统一校验入口。
// 包括：
//   - 全部白名单数值的 NaN/Inf 检查；
//   - 范围与上下限次序；
//   - 跨字段约束（SV ≤ tank2.height、pid 上下限等）；
//   - 不可达目标流量（BLOCKING）；
//   - Tank 1 预计溢流（BLOCKING）。
func ValidateTemplateConfig(cfg TemplateConfig) []ValidationIssue {
	var errs []ValidationIssue

	// NaN/Inf
	if !isFinite(cfg.CycleTime) {
		errs = append(errs, ValidationIssue{Path: "cycleTime", Level: "error", Message: "cycleTime 必须是有限数"})
	}
	if !isFinite(cfg.SourceFlow) {
		errs = append(errs, ValidationIssue{Path: "sourceFlow", Level: "error", Message: "sourceFlow 必须是有限数"})
	}
	for _, k := range []string{"fullTravelTime", "initialOpening", "flowCoefficient", "minOpening", "maxOpening"} {
		v := getFloatField(cfg.Valve, k)
		if !isFinite(v) {
			errs = append(errs, ValidationIssue{Path: "valve." + k, Level: "error", Message: "必须是有限数"})
		}
	}
	for _, prefix := range []string{"tank1", "tank2"} {
		var t TankConfig
		if prefix == "tank1" {
			t = cfg.Tank1
		} else {
			t = cfg.Tank2
		}
		for _, k := range []string{"height", "radius", "outletArea", "initialLevel"} {
			v := getFloatField(t, k)
			if !isFinite(v) {
				errs = append(errs, ValidationIssue{Path: prefix + "." + k, Level: "error", Message: "必须是有限数"})
			}
		}
	}
	for _, k := range []string{"PB", "TI", "TD", "KD", "SV", "MV",
		"SVSCL", "SVSCH", "SVL", "SVH", "MVSCL", "MVSCH", "MVL", "MVH"} {
		v := getFloatField(cfg.PID, k)
		if !isFinite(v) {
			errs = append(errs, ValidationIssue{Path: "pid." + k, Level: "error", Message: "必须是有限数"})
		}
	}

	// 基础范围
	if isFinite(cfg.CycleTime) && cfg.CycleTime <= 0 {
		errs = append(errs, ValidationIssue{Path: "cycleTime", Level: "error", Message: "cycleTime 必须 > 0"})
	}
	if isFinite(cfg.SourceFlow) && cfg.SourceFlow < 0 {
		errs = append(errs, ValidationIssue{Path: "sourceFlow", Level: "error", Message: "sourceFlow 必须 >= 0"})
	}
	if isFinite(cfg.Valve.MinOpening) && isFinite(cfg.Valve.MaxOpening) && cfg.Valve.MinOpening >= cfg.Valve.MaxOpening {
		errs = append(errs, ValidationIssue{Path: "valve.minOpening", Level: "error", Message: "valve.minOpening 必须 < maxOpening"})
	}
	if isFinite(cfg.Valve.MinOpening) && (cfg.Valve.MinOpening < 0 || cfg.Valve.MinOpening > 100) {
		errs = append(errs, ValidationIssue{Path: "valve.minOpening", Level: "error", Message: "valve.minOpening 须在 [0, 100]"})
	}
	if isFinite(cfg.Valve.MaxOpening) && (cfg.Valve.MaxOpening < 0 || cfg.Valve.MaxOpening > 100) {
		errs = append(errs, ValidationIssue{Path: "valve.maxOpening", Level: "error", Message: "valve.maxOpening 须在 [0, 100]"})
	}
	if isFinite(cfg.Valve.InitialOpening) && isFinite(cfg.Valve.MinOpening) && isFinite(cfg.Valve.MaxOpening) &&
		(cfg.Valve.InitialOpening < cfg.Valve.MinOpening || cfg.Valve.InitialOpening > cfg.Valve.MaxOpening) {
		errs = append(errs, ValidationIssue{Path: "valve.initialOpening", Level: "error", Message: "valve.initialOpening 超出 [minOpening, maxOpening]"})
	}
	if isFinite(cfg.Valve.FlowCoefficient) && cfg.Valve.FlowCoefficient < 0 {
		errs = append(errs, ValidationIssue{Path: "valve.flowCoefficient", Level: "error", Message: "valve.flowCoefficient 必须 >= 0"})
	}
	if isFinite(cfg.Valve.FullTravelTime) && cfg.Valve.FullTravelTime < 0 {
		errs = append(errs, ValidationIssue{Path: "valve.fullTravelTime", Level: "error", Message: "valve.fullTravelTime 必须 >= 0"})
	}

	// 水箱
	for _, prefix := range []string{"tank1", "tank2"} {
		var t TankConfig
		if prefix == "tank1" {
			t = cfg.Tank1
		} else {
			t = cfg.Tank2
		}
		if isFinite(t.Height) && t.Height <= 0 {
			errs = append(errs, ValidationIssue{Path: prefix + ".height", Level: "error", Message: "height 必须 > 0"})
		}
		if isFinite(t.Radius) && t.Radius <= 0 {
			errs = append(errs, ValidationIssue{Path: prefix + ".radius", Level: "error", Message: "radius 必须 > 0"})
		}
		if isFinite(t.OutletArea) && t.OutletArea <= 0 {
			errs = append(errs, ValidationIssue{Path: prefix + ".outletArea", Level: "error", Message: "outletArea 必须 > 0"})
		}
		if isFinite(t.InitialLevel) && isFinite(t.Height) && (t.InitialLevel < 0 || t.InitialLevel > t.Height) {
			errs = append(errs, ValidationIssue{Path: prefix + ".initialLevel", Level: "error", Message: "initialLevel 须在 [0, height]"})
		}
	}

	// PID 范围
	pid := cfg.PID
	if isFinite(pid.PB) && pid.PB <= 0 {
		errs = append(errs, ValidationIssue{Path: "pid.PB", Level: "error", Message: "pid.PB 必须 > 0"})
	}
	if isFinite(pid.TI) && pid.TI < 0 {
		errs = append(errs, ValidationIssue{Path: "pid.TI", Level: "error", Message: "pid.TI 必须 >= 0"})
	}
	if isFinite(pid.TD) && pid.TD < 0 {
		errs = append(errs, ValidationIssue{Path: "pid.TD", Level: "error", Message: "pid.TD 必须 >= 0"})
	}
	if isFinite(pid.KD) && pid.KD <= 0 {
		errs = append(errs, ValidationIssue{Path: "pid.KD", Level: "error", Message: "pid.KD 必须 > 0"})
	}
	if pid.MODE < 1 || pid.MODE > 8 {
		errs = append(errs, ValidationIssue{Path: "pid.MODE", Level: "error", Message: "pid.MODE 必须是 1..8 的整数"})
	}
	if pid.SWPN != 0 && pid.SWPN != 1 {
		errs = append(errs, ValidationIssue{Path: "pid.SWPN", Level: "error", Message: "pid.SWPN 必须为 0 或 1"})
	}
	if isFinite(pid.SVSCL) && isFinite(pid.SVSCH) && pid.SVSCH <= pid.SVSCL {
		errs = append(errs, ValidationIssue{Path: "pid.SVSCH", Level: "error", Message: "pid.SVSCH 必须 > SVSCL"})
	}
	if isFinite(pid.SVL) && isFinite(pid.SVH) && pid.SVH < pid.SVL {
		errs = append(errs, ValidationIssue{Path: "pid.SVH", Level: "error", Message: "pid.SVH 必须 >= SVL"})
	}
	if isFinite(pid.MVSCL) && isFinite(pid.MVSCH) && pid.MVSCH <= pid.MVSCL {
		errs = append(errs, ValidationIssue{Path: "pid.MVSCH", Level: "error", Message: "pid.MVSCH 必须 > MVSCL"})
	}
	if isFinite(pid.MVL) && isFinite(pid.MVH) && pid.MVH < pid.MVL {
		errs = append(errs, ValidationIssue{Path: "pid.MVH", Level: "error", Message: "pid.MVH 必须 >= MVL"})
	}
	if isFinite(pid.SV) && isFinite(pid.SVL) && isFinite(pid.SVH) && (pid.SV < pid.SVL || pid.SV > pid.SVH) {
		errs = append(errs, ValidationIssue{Path: "pid.SV", Level: "error", Message: "pid.SV 须在 [SVL, SVH]"})
	}
	if isFinite(pid.MV) && isFinite(pid.MVL) && isFinite(pid.MVH) && (pid.MV < pid.MVL || pid.MV > pid.MVH) {
		errs = append(errs, ValidationIssue{Path: "pid.MV", Level: "error", Message: "pid.MV 须在 [MVL, MVH]"})
	}
	if isFinite(pid.SVL) && isFinite(pid.SVH) && isFinite(pid.SVSCL) && isFinite(pid.SVSCH) &&
		(pid.SVL < pid.SVSCL || pid.SVH > pid.SVSCH) {
		errs = append(errs, ValidationIssue{Path: "pid.SVL", Level: "error", Message: "pid.SVL/SVH 须位于 [SVSCL, SVSCH]"})
	}
	if isFinite(pid.MVL) && isFinite(pid.MVH) && isFinite(pid.MVSCL) && isFinite(pid.MVSCH) &&
		(pid.MVL < pid.MVSCL || pid.MVH > pid.MVSCH) {
		errs = append(errs, ValidationIssue{Path: "pid.MVL", Level: "error", Message: "pid.MVL/MVH 须位于 [MVSCL, MVSCH]"})
	}

	// 跨字段约束：SV/SVH 必须 <= tank2.height。
	if isFinite(cfg.Tank2.Height) {
		if isFinite(pid.SVH) && pid.SVH > cfg.Tank2.Height {
			errs = append(errs, ValidationIssue{Path: "pid.SVH", Level: "error", Message: "pid.SVH 不得超过 tank2.height"})
		}
		if isFinite(pid.SV) && pid.SV > cfg.Tank2.Height {
			errs = append(errs, ValidationIssue{Path: "pid.SV", Level: "error", Message: "pid.SV 不得超过 tank2.height"})
		}
	}

	// 跨字段约束：不可达目标流量（BLOCKING）。
	q2 := torricelliOutflow(cfg.Tank2.OutletArea, pid.SV)
	maxSupply := cfg.SourceFlow * cfg.Valve.FlowCoefficient
	if maxSupply < q2 {
		errs = append(errs, ValidationIssue{
			Path:    "sourceFlow",
			Level:   "error",
			Message: fmt.Sprintf("目标稳态流量超过水源最大供给 (需要 %.6f m³/s, 最大 %.6f)", q2, maxSupply),
		})
	}

	// 跨字段约束：Tank 1 预计溢流（BLOCKING）。
	tank1Lvl := tank1SteadyLevel(q2, cfg.Tank1.OutletArea)
	if tank1Lvl > cfg.Tank1.Height {
		errs = append(errs, ValidationIssue{
			Path:    "tank1.outletArea",
			Level:   "error",
			Message: fmt.Sprintf("预计 Tank 1 稳态液位 %.3f m 超过水箱高度 %.3f m", tank1Lvl, cfg.Tank1.Height),
		})
	}

	return errs
}

// materialize 把 yaml.Node 转换为可编辑的 TemplateDocument，并完成 topology 校验。
func (s *TemplateService) materialize(absPath string, raw []byte, node *yaml.Node) (TemplateDocument, error) {
	rootMap := topLevelMapping(node)
	if rootMap == nil {
		return TemplateDocument{}, fmt.Errorf("YAML 顶层必须是 mapping")
	}
	programNode := mappingValue(rootMap, "program")
	if programNode == nil || programNode.Kind != yaml.SequenceNode {
		return TemplateDocument{}, fmt.Errorf("YAML 必须包含 program 列表")
	}
	if err := validateEditableScalarTypes(rootMap, programNode); err != nil {
		return TemplateDocument{}, err
	}

	topology, topoErr := buildTopology(programNode)
	if topoErr != nil {
		return TemplateDocument{}, topoErr
	}

	cfg, presence, warns := extractConfig(rootMap, programNode, topology)

	return TemplateDocument{
		Path:        absPath,
		ContentHash: hashBytes(raw),
		Config:      cfg,
		Presence:    presence,
		Topology:    topology,
		Warnings:    warns,
		Raw:         node,
	}, nil
}

// validateEditableScalarTypes rejects malformed values before defaults are
// applied. In particular, an invalid-but-present optional value must never be
// mistaken for a missing value and silently replaced with a Python default.
func validateEditableScalarTypes(rootMap, programNode *yaml.Node) error {
	type fieldSpec struct {
		path    string
		node    *yaml.Node
		key     string
		integer bool
	}
	var fields []fieldSpec
	clock := mappingValue(rootMap, "clock")
	fields = append(fields, fieldSpec{path: "clock.cycle_time", node: clock, key: "cycle_time"})

	programs := make(map[string]*yaml.Node, len(programNode.Content))
	for _, pn := range programNode.Content {
		if name := mappingStringValue(pn, "name"); name != "" {
			programs[name] = pn
		}
	}
	fields = append(fields, fieldSpec{path: "program.source_flow.value", node: programs["source_flow"], key: "value"})

	appendParams := func(programName string, specs ...fieldSpec) {
		params := mappingValue(programs[programName], "params")
		for _, spec := range specs {
			spec.node = params
			fields = append(fields, spec)
		}
	}
	appendParams("valve_1",
		fieldSpec{path: "program.valve_1.params.full_travel_time", key: "full_travel_time"},
		fieldSpec{path: "program.valve_1.params.initial_opening", key: "initial_opening"},
		fieldSpec{path: "program.valve_1.params.flow_coefficient", key: "flow_coefficient"},
		fieldSpec{path: "program.valve_1.params.min_opening", key: "min_opening"},
		fieldSpec{path: "program.valve_1.params.max_opening", key: "max_opening"},
	)
	for _, name := range []string{"tank_1", "tank_2"} {
		appendParams(name,
			fieldSpec{path: "program." + name + ".params.height", key: "height"},
			fieldSpec{path: "program." + name + ".params.radius", key: "radius"},
			fieldSpec{path: "program." + name + ".params.outlet_area", key: "outlet_area"},
			fieldSpec{path: "program." + name + ".params.initial_level", key: "initial_level"},
		)
	}
	for _, key := range []string{"PB", "TI", "TD", "KD", "SV", "MV", "MODE", "SWPN", "SVSCL", "SVSCH", "SVL", "SVH", "MVSCL", "MVSCH", "MVL", "MVH"} {
		appendParams("pid2", fieldSpec{
			path:    "program.pid2.params." + key,
			key:     key,
			integer: key == "MODE" || key == "SWPN",
		})
	}

	for _, field := range fields {
		value := mappingValue(field.node, field.key)
		if value == nil {
			continue
		}
		if value.Kind != yaml.ScalarNode || (value.Tag != "!!int" && value.Tag != "!!float") {
			return fmt.Errorf("%s 必须是 YAML 数值", field.path)
		}
		number, err := strconv.ParseFloat(value.Value, 64)
		if err != nil {
			return fmt.Errorf("%s 不能解析为数值: %w", field.path, err)
		}
		if field.integer && number != math.Trunc(number) {
			return fmt.Errorf("%s 必须是整数", field.path)
		}
	}
	return nil
}

// buildTopology 校验 program 列表与固定拓扑是否匹配。
func buildTopology(programNode *yaml.Node) (TemplateTopology, error) {
	indexed := make(map[string]yaml.Node, len(programNode.Content))
	for i := range programNode.Content {
		pn := programNode.Content[i]
		if pn.Kind != yaml.MappingNode {
			return TemplateTopology{}, fmt.Errorf("program[%d] 必须是 mapping", i)
		}
		name := mappingStringValue(pn, "name")
		if name == "" {
			return TemplateTopology{}, fmt.Errorf("program[%d] 缺少 name", i)
		}
		if _, dup := indexed[name]; dup {
			return TemplateTopology{}, fmt.Errorf("program name 重复: %s", name)
		}
		indexed[name] = *pn
	}

	result := TemplateTopology{Programs: make([]TemplateProgramTopology, 0, len(fixedTopology))}
	for _, expected := range fixedTopology {
		pn, ok := indexed[expected.name]
		if !ok {
			return TemplateTopology{}, fmt.Errorf("缺失固定 program: %s", expected.name)
		}
		gotType := strings.ToUpper(mappingStringValue(&pn, "type"))
		if gotType != strings.ToUpper(expected.typeStr) {
			return TemplateTopology{}, fmt.Errorf("program %s 类型应为 %s, 实际为 %s",
				expected.name, expected.typeStr, gotType)
		}

		inputsNode := mappingValue(&pn, "inputs")
		gotInputs := map[string]string{}
		if inputsNode != nil && inputsNode.Kind == yaml.MappingNode {
			for i := 0; i < len(inputsNode.Content); i += 2 {
				k := inputsNode.Content[i].Value
				v := mappingStringValue(inputsNode, k)
				gotInputs[k] = v
			}
		}
		if !mapsEqual(gotInputs, expected.inputs) {
			return TemplateTopology{}, fmt.Errorf("program %s inputs 与模板不匹配 (got=%v want=%v)",
				expected.name, gotInputs, expected.inputs)
		}

		ef := mappingBoolValue(&pn, "execute_first")
		if ef != expected.executeFirst {
			return TemplateTopology{}, fmt.Errorf("program %s execute_first 应为 %v, 实际为 %v",
				expected.name, expected.executeFirst, ef)
		}

		result.Programs = append(result.Programs, TemplateProgramTopology{
			Name:         expected.name,
			Type:         strings.ToUpper(expected.typeStr),
			Inputs:       expected.inputs,
			ExecuteFirst: expected.executeFirst,
		})
	}

	for name := range indexed {
		found := false
		for _, expected := range fixedTopology {
			if expected.name == name {
				found = true
				break
			}
		}
		if !found {
			return TemplateTopology{}, fmt.Errorf("存在非固定 program: %s", name)
		}
	}

	return result, nil
}

// extractConfig 从 root 与 program 中抽取规范化字段，并记录每个字段是否真实存在于 YAML。
// 缺失的阀门字段按 Python VALVE.default_params 填入；其他字段缺失时填 0。
func extractConfig(rootMap, programNode *yaml.Node, topology TemplateTopology) (TemplateConfig, FieldPresence, []string) {
	warnings := []string{}
	var presence FieldPresence

	clockNode := mappingValue(rootMap, "clock")
	clockMode, cycleTime := "", 0.0
	if clockNode != nil && clockNode.Kind == yaml.MappingNode {
		if v, ok := lookupFloat(clockNode, "cycle_time"); ok {
			cycleTime = v
			presence.CycleTime = true
		}
		if v, ok := lookupString(clockNode, "mode"); ok {
			clockMode = v
			presence.ClockMode = true
		}
	}

	cfg := TemplateConfig{
		ClockMode: clockMode,
		CycleTime: cycleTime,
	}

	programByName := make(map[string]yaml.Node, len(programNode.Content))
	for i := range programNode.Content {
		pn := programNode.Content[i]
		name := mappingStringValue(pn, "name")
		if name != "" {
			programByName[name] = *pn
		}
	}

	if pn, ok := programByName["source_flow"]; ok {
		if v, ok := lookupFloat(&pn, "value"); ok {
			cfg.SourceFlow = v
			presence.SourceFlow = true
		}
	}

	if pn, ok := programByName["valve_1"]; ok {
		paramsNode := mappingValue(&pn, "params")
		cfg.Valve, presence.Valve = extractValve(paramsNode)
	}

	if pn, ok := programByName["tank_1"]; ok {
		paramsNode := mappingValue(&pn, "params")
		cfg.Tank1, presence.Tank1 = extractTank(paramsNode)
	}
	if pn, ok := programByName["tank_2"]; ok {
		paramsNode := mappingValue(&pn, "params")
		cfg.Tank2, presence.Tank2 = extractTank(paramsNode)
	}

	if pn, ok := programByName["pid2"]; ok {
		paramsNode := mappingValue(&pn, "params")
		cfg.PID, presence.PID = extractPID(paramsNode)
	}

	return cfg, presence, warnings
}

func extractValve(params *yaml.Node) (ValveConfig, ValvePresence) {
	cfg := pythonValveDefaults
	var p ValvePresence
	if v, ok := lookupFloat(params, "full_travel_time"); ok {
		cfg.FullTravelTime = v
		p.FullTravelTime = true
	}
	if v, ok := lookupFloat(params, "initial_opening"); ok {
		cfg.InitialOpening = v
		p.InitialOpening = true
	}
	if v, ok := lookupFloat(params, "flow_coefficient"); ok {
		cfg.FlowCoefficient = v
		p.FlowCoefficient = true
	}
	if v, ok := lookupFloat(params, "min_opening"); ok {
		cfg.MinOpening = v
		p.MinOpening = true
	}
	if v, ok := lookupFloat(params, "max_opening"); ok {
		cfg.MaxOpening = v
		p.MaxOpening = true
	}
	return cfg, p
}

func extractTank(params *yaml.Node) (TankConfig, TankPresence) {
	var cfg TankConfig
	var p TankPresence
	if v, ok := lookupFloat(params, "height"); ok {
		cfg.Height = v
		p.Height = true
	}
	if v, ok := lookupFloat(params, "radius"); ok {
		cfg.Radius = v
		p.Radius = true
	}
	if v, ok := lookupFloat(params, "outlet_area"); ok {
		cfg.OutletArea = v
		p.OutletArea = true
	}
	if v, ok := lookupFloat(params, "initial_level"); ok {
		cfg.InitialLevel = v
		p.InitialLevel = true
	}
	return cfg, p
}

func extractPID(params *yaml.Node) (PIDConfig, PIDPresence) {
	var cfg PIDConfig
	var p PIDPresence
	// 注意：PV 是运行时只读字段，不进入 cfg 与 presence；写盘阶段永不触碰。
	if v, ok := lookupFloat(params, "PB"); ok {
		cfg.PB = v
		p.PB = true
	}
	if v, ok := lookupFloat(params, "TI"); ok {
		cfg.TI = v
		p.TI = true
	}
	if v, ok := lookupFloat(params, "TD"); ok {
		cfg.TD = v
		p.TD = true
	}
	if v, ok := lookupFloat(params, "KD"); ok {
		cfg.KD = v
		p.KD = true
	}
	if v, ok := lookupFloat(params, "SV"); ok {
		cfg.SV = v
		p.SV = true
	}
	if v, ok := lookupFloat(params, "MV"); ok {
		cfg.MV = v
		p.MV = true
	}
	if v, ok := lookupFloat(params, "MODE"); ok {
		cfg.MODE = int(v)
		p.MODE = true
	}
	if v, ok := lookupFloat(params, "SWPN"); ok {
		cfg.SWPN = int(v)
		p.SWPN = true
	}
	if v, ok := lookupFloat(params, "SVSCL"); ok {
		cfg.SVSCL = v
		p.SVSCL = true
	}
	if v, ok := lookupFloat(params, "SVSCH"); ok {
		cfg.SVSCH = v
		p.SVSCH = true
	}
	if v, ok := lookupFloat(params, "SVL"); ok {
		cfg.SVL = v
		p.SVL = true
	}
	if v, ok := lookupFloat(params, "SVH"); ok {
		cfg.SVH = v
		p.SVH = true
	}
	if v, ok := lookupFloat(params, "MVSCL"); ok {
		cfg.MVSCL = v
		p.MVSCL = true
	}
	if v, ok := lookupFloat(params, "MVSCH"); ok {
		cfg.MVSCH = v
		p.MVSCH = true
	}
	if v, ok := lookupFloat(params, "MVL"); ok {
		cfg.MVL = v
		p.MVL = true
	}
	if v, ok := lookupFloat(params, "MVH"); ok {
		cfg.MVH = v
		p.MVH = true
	}
	return cfg, p
}

// applyPatchesToConfig 按白名单 path 应用 patches，返回新 cfg、实际修改的路径集合与错误。
// 实际修改的判定：补丁后的 cfg 与补丁前的 cfg 在该路径上值不同（含被 tank2.height 联动触发的
// pid.SVSCH/SVH）。白名单外的 path 直接返回错误。
func applyPatchesToConfig(cfg TemplateConfig, patches []TemplatePatch) (TemplateConfig, []string, error) {
	modified := []string{}
	for _, p := range patches {
		updated, changed, err := applyOne(cfg, p)
		if err != nil {
			return cfg, nil, fmt.Errorf("patch %q: %w", p.Path, err)
		}
		if changed {
			modified = append(modified, p.Path)
		}
		cfg = updated
	}
	return cfg, modified, nil
}

// applyOne 返回新 cfg、字段是否实际变更、错误。
// 任意一条 patch 失败即中止：即使后续 patch 在该 cfg 上仍能 apply 也不重做。
func applyOne(cfg TemplateConfig, p TemplatePatch) (TemplateConfig, bool, error) {
	path := strings.TrimSpace(p.Path)
	if path == "" {
		return cfg, false, errors.New("path 不能为空")
	}
	if !isFinite(p.Value) {
		return cfg, false, fmt.Errorf("value 必须是有限数")
	}
	switch path {
	case "cycleTime":
		if p.Value <= 0 {
			return cfg, false, errors.New("cycleTime 必须 > 0")
		}
		if cfg.CycleTime == p.Value {
			return cfg, false, nil
		}
		cfg.CycleTime = p.Value
		return cfg, true, nil
	case "sourceFlow":
		if p.Value < 0 {
			return cfg, false, errors.New("sourceFlow 必须 >= 0")
		}
		if cfg.SourceFlow == p.Value {
			return cfg, false, nil
		}
		cfg.SourceFlow = p.Value
		return cfg, true, nil
	case "valve.fullTravelTime":
		if p.Value < 0 {
			return cfg, false, errors.New("valve.fullTravelTime 必须 >= 0")
		}
		if cfg.Valve.FullTravelTime == p.Value {
			return cfg, false, nil
		}
		cfg.Valve.FullTravelTime = p.Value
		return cfg, true, nil
	case "valve.initialOpening":
		if cfg.Valve.InitialOpening == p.Value {
			return cfg, false, nil
		}
		cfg.Valve.InitialOpening = p.Value
		return cfg, true, nil
	case "valve.flowCoefficient":
		if p.Value < 0 {
			return cfg, false, errors.New("valve.flowCoefficient 必须 >= 0")
		}
		if cfg.Valve.FlowCoefficient == p.Value {
			return cfg, false, nil
		}
		cfg.Valve.FlowCoefficient = p.Value
		return cfg, true, nil
	case "valve.minOpening":
		if p.Value < 0 || p.Value > 100 {
			return cfg, false, errors.New("valve.minOpening 须在 [0, 100]")
		}
		if cfg.Valve.MinOpening == p.Value {
			return cfg, false, nil
		}
		cfg.Valve.MinOpening = p.Value
		return cfg, true, nil
	case "valve.maxOpening":
		if p.Value < 0 || p.Value > 100 {
			return cfg, false, errors.New("valve.maxOpening 须在 [0, 100]")
		}
		if cfg.Valve.MaxOpening == p.Value {
			return cfg, false, nil
		}
		cfg.Valve.MaxOpening = p.Value
		return cfg, true, nil
	case "tank1.height":
		if p.Value <= 0 {
			return cfg, false, errors.New("tank1.height 必须 > 0")
		}
		if cfg.Tank1.Height == p.Value {
			return cfg, false, nil
		}
		cfg.Tank1.Height = p.Value
		return cfg, true, nil
	case "tank1.radius":
		if p.Value <= 0 {
			return cfg, false, errors.New("tank1.radius 必须 > 0")
		}
		if cfg.Tank1.Radius == p.Value {
			return cfg, false, nil
		}
		cfg.Tank1.Radius = p.Value
		return cfg, true, nil
	case "tank1.outletArea":
		if p.Value <= 0 {
			return cfg, false, errors.New("tank1.outletArea 必须 > 0")
		}
		if cfg.Tank1.OutletArea == p.Value {
			return cfg, false, nil
		}
		cfg.Tank1.OutletArea = p.Value
		return cfg, true, nil
	case "tank1.initialLevel":
		if p.Value < 0 {
			return cfg, false, errors.New("tank1.initialLevel 必须 >= 0")
		}
		if cfg.Tank1.InitialLevel == p.Value {
			return cfg, false, nil
		}
		cfg.Tank1.InitialLevel = p.Value
		return cfg, true, nil
	case "tank2.height":
		if p.Value <= 0 {
			return cfg, false, errors.New("tank2.height 必须 > 0")
		}
		changed := cfg.Tank2.Height != p.Value
		cfg.Tank2.Height = p.Value
		// 高度实际变化时始终联动 SVSCH/SVH，不能因其中一个字段碰巧相等而漏掉另一个。
		if changed {
			cfg.PID.SVSCH = p.Value
			cfg.PID.SVH = p.Value
		}
		return cfg, changed, nil
	case "tank2.radius":
		if p.Value <= 0 {
			return cfg, false, errors.New("tank2.radius 必须 > 0")
		}
		if cfg.Tank2.Radius == p.Value {
			return cfg, false, nil
		}
		cfg.Tank2.Radius = p.Value
		return cfg, true, nil
	case "tank2.outletArea":
		if p.Value <= 0 {
			return cfg, false, errors.New("tank2.outletArea 必须 > 0")
		}
		if cfg.Tank2.OutletArea == p.Value {
			return cfg, false, nil
		}
		cfg.Tank2.OutletArea = p.Value
		return cfg, true, nil
	case "tank2.initialLevel":
		if p.Value < 0 {
			return cfg, false, errors.New("tank2.initialLevel 必须 >= 0")
		}
		if cfg.Tank2.InitialLevel == p.Value {
			return cfg, false, nil
		}
		cfg.Tank2.InitialLevel = p.Value
		return cfg, true, nil
	default:
		field, ok := pidPath(path)
		if !ok {
			return cfg, false, fmt.Errorf("非白名单路径")
		}
		prev, _ := getPIDField(cfg.PID, field)
		if err := setPIDField(&cfg.PID, field, p.Value); err != nil {
			return cfg, false, err
		}
		after, _ := getPIDField(cfg.PID, field)
		return cfg, prev != after, nil
	}
}

// pidPath 把 "pid.PB" / "pid.MODE" 转为 PIDConfig 字段名。
func pidPath(p string) (string, bool) {
	const prefix = "pid."
	if !strings.HasPrefix(p, prefix) {
		return "", false
	}
	field := strings.TrimPrefix(p, prefix)
	switch field {
	case "PB", "TI", "TD", "KD", "SV", "MV",
		"MODE", "SWPN",
		"SVSCL", "SVSCH", "SVL", "SVH",
		"MVSCL", "MVSCH", "MVL", "MVH":
		return field, true
	}
	return "", false
}

// setPIDField 写入 PID 字段（含合法性校验）。
func setPIDField(p *PIDConfig, field string, v float64) error {
	switch field {
	case "PB":
		if v <= 0 {
			return errors.New("pid.PB 必须 > 0")
		}
		p.PB = v
	case "TI":
		if v < 0 {
			return errors.New("pid.TI 必须 >= 0")
		}
		p.TI = v
	case "TD":
		if v < 0 {
			return errors.New("pid.TD 必须 >= 0")
		}
		p.TD = v
	case "KD":
		if v <= 0 {
			return errors.New("pid.KD 必须 > 0")
		}
		p.KD = v
	case "SV":
		p.SV = v
	case "MV":
		p.MV = v
	case "MODE":
		iv := int(v)
		if iv < 1 || iv > 8 || float64(iv) != v {
			return errors.New("pid.MODE 必须是 1..8 的整数")
		}
		p.MODE = iv
	case "SWPN":
		iv := int(v)
		if iv != 0 && iv != 1 {
			return errors.New("pid.SWPN 必须为 0 或 1")
		}
		p.SWPN = iv
	case "SVSCL":
		p.SVSCL = v
	case "SVSCH":
		p.SVSCH = v
	case "SVL":
		p.SVL = v
	case "SVH":
		p.SVH = v
	case "MVSCL":
		p.MVSCL = v
	case "MVSCH":
		p.MVSCH = v
	case "MVL":
		p.MVL = v
	case "MVH":
		p.MVH = v
	}
	return nil
}

// getPIDField 读取 PID 字段值（用于变化判定）。
func getPIDField(p PIDConfig, field string) (float64, bool) {
	switch field {
	case "PB":
		return p.PB, true
	case "TI":
		return p.TI, true
	case "TD":
		return p.TD, true
	case "KD":
		return p.KD, true
	case "SV":
		return p.SV, true
	case "MV":
		return p.MV, true
	case "MODE":
		return float64(p.MODE), true
	case "SWPN":
		return float64(p.SWPN), true
	case "SVSCL":
		return p.SVSCL, true
	case "SVSCH":
		return p.SVSCH, true
	case "SVL":
		return p.SVL, true
	case "SVH":
		return p.SVH, true
	case "MVSCL":
		return p.MVSCL, true
	case "MVSCH":
		return p.MVSCH, true
	case "MVL":
		return p.MVL, true
	case "MVH":
		return p.MVH, true
	}
	return 0, false
}

// getFloatField 通过反射读取 TankConfig/ValveConfig 的字段值（仅用于统一校验）。
func getFloatField(v any, name string) float64 {
	switch s := v.(type) {
	case ValveConfig:
		switch name {
		case "fullTravelTime":
			return s.FullTravelTime
		case "initialOpening":
			return s.InitialOpening
		case "flowCoefficient":
			return s.FlowCoefficient
		case "minOpening":
			return s.MinOpening
		case "maxOpening":
			return s.MaxOpening
		}
	case TankConfig:
		switch name {
		case "height":
			return s.Height
		case "radius":
			return s.Radius
		case "outletArea":
			return s.OutletArea
		case "initialLevel":
			return s.InitialLevel
		}
	case PIDConfig:
		switch name {
		case "PB":
			return s.PB
		case "TI":
			return s.TI
		case "TD":
			return s.TD
		case "KD":
			return s.KD
		case "SV":
			return s.SV
		case "MV":
			return s.MV
		case "MODE":
			return float64(s.MODE)
		case "SWPN":
			return float64(s.SWPN)
		case "SVSCL":
			return s.SVSCL
		case "SVSCH":
			return s.SVSCH
		case "SVL":
			return s.SVL
		case "SVH":
			return s.SVH
		case "MVSCL":
			return s.MVSCL
		case "MVSCH":
			return s.MVSCH
		case "MVL":
			return s.MVL
		case "MVH":
			return s.MVH
		}
	}
	return 0
}

// writeConfigIntoNode 仅修改 modifiedPaths 中列出的字段叶子；其他字段、注释、未知键、
// program 顺序、display_args、inputs、execute_first 全部不动。
//
// 关键约束：
//   - 绝不为缺失字段补默认值键；只在原 YAML 已存在该键或本次 modifiedPaths 要求时写。
//   - 绝不写 pid.PV（PV 是运行时只读字段，不属于可写白名单）。
//   - tank2.height 联动触发的 pid.SVSCH/SVH 写入由调用方在 modifiedPaths 中明确包含。
func writeConfigIntoNode(root *yaml.Node, cfg TemplateConfig, modifiedPaths []string) error {
	rootMap := topLevelMapping(root)
	if rootMap == nil {
		return errors.New("root 不是 mapping")
	}
	modified := make(map[string]bool, len(modifiedPaths))
	for _, p := range modifiedPaths {
		modified[p] = true
	}
	// 高度联动必须顺带写入的字段。
	if modified["tank2.height"] {
		modified["pid.SVSCH"] = true
		modified["pid.SVH"] = true
	}

	// clock
	if modified["cycleTime"] || modified["clockMode"] {
		clockNode := mappingValue(rootMap, "clock")
		if clockNode == nil {
			return errors.New("clock 节点缺失，无法写入 cycleTime/clockMode")
		}
		if modified["cycleTime"] {
			setMappingFloat(clockNode, "cycle_time", cfg.CycleTime)
		}
		if modified["clockMode"] {
			setMappingString(clockNode, "mode", cfg.ClockMode)
		}
	}

	programNode := mappingValue(rootMap, "program")
	if programNode == nil || programNode.Kind != yaml.SequenceNode {
		return errors.New("program 节点缺失")
	}

	programByName := make(map[string]*yaml.Node, len(programNode.Content))
	for i := range programNode.Content {
		pn := programNode.Content[i]
		name := mappingStringValue(pn, "name")
		if name != "" {
			programByName[name] = pn
		}
	}

	if modified["sourceFlow"] {
		pn, ok := programByName["source_flow"]
		if !ok {
			return errors.New("source_flow 节点缺失")
		}
		setMappingFloat(pn, "value", cfg.SourceFlow)
	}

	if valveChanged(modified) {
		pn, ok := programByName["valve_1"]
		if !ok {
			return errors.New("valve_1 节点缺失")
		}
		paramsNode := mappingValue(pn, "params")
		if paramsNode == nil {
			return errors.New("valve_1.params 节点缺失")
		}
		if modified["valve.fullTravelTime"] {
			setMappingFloat(paramsNode, "full_travel_time", cfg.Valve.FullTravelTime)
		}
		if modified["valve.initialOpening"] {
			setMappingFloat(paramsNode, "initial_opening", cfg.Valve.InitialOpening)
		}
		if modified["valve.flowCoefficient"] {
			setMappingFloat(paramsNode, "flow_coefficient", cfg.Valve.FlowCoefficient)
		}
		if modified["valve.minOpening"] {
			setMappingFloat(paramsNode, "min_opening", cfg.Valve.MinOpening)
		}
		if modified["valve.maxOpening"] {
			setMappingFloat(paramsNode, "max_opening", cfg.Valve.MaxOpening)
		}
	}

	if tankChanged("tank1", modified) {
		pn, ok := programByName["tank_1"]
		if !ok {
			return errors.New("tank_1 节点缺失")
		}
		paramsNode := mappingValue(pn, "params")
		if paramsNode == nil {
			return errors.New("tank_1.params 节点缺失")
		}
		if modified["tank1.height"] {
			setMappingFloat(paramsNode, "height", cfg.Tank1.Height)
		}
		if modified["tank1.radius"] {
			setMappingFloat(paramsNode, "radius", cfg.Tank1.Radius)
		}
		if modified["tank1.outletArea"] {
			setMappingFloat(paramsNode, "outlet_area", cfg.Tank1.OutletArea)
		}
		if modified["tank1.initialLevel"] {
			setMappingFloat(paramsNode, "initial_level", cfg.Tank1.InitialLevel)
		}
	}

	if tankChanged("tank2", modified) {
		pn, ok := programByName["tank_2"]
		if !ok {
			return errors.New("tank_2 节点缺失")
		}
		paramsNode := mappingValue(pn, "params")
		if paramsNode == nil {
			return errors.New("tank_2.params 节点缺失")
		}
		if modified["tank2.height"] {
			setMappingFloat(paramsNode, "height", cfg.Tank2.Height)
		}
		if modified["tank2.radius"] {
			setMappingFloat(paramsNode, "radius", cfg.Tank2.Radius)
		}
		if modified["tank2.outletArea"] {
			setMappingFloat(paramsNode, "outlet_area", cfg.Tank2.OutletArea)
		}
		if modified["tank2.initialLevel"] {
			setMappingFloat(paramsNode, "initial_level", cfg.Tank2.InitialLevel)
		}
	}

	if pidChanged(modified) {
		pn, ok := programByName["pid2"]
		if !ok {
			return errors.New("pid2 节点缺失")
		}
		paramsNode := mappingValue(pn, "params")
		if paramsNode == nil {
			return errors.New("pid2.params 节点缺失")
		}
		// 只写本次实际修改的 PID 字段；存在但未修改的标量也不得重新格式化。
		pidFieldWrites := []struct {
			key  string
			path string
			val  float64
		}{
			{"PB", "pid.PB", cfg.PID.PB},
			{"TI", "pid.TI", cfg.PID.TI},
			{"TD", "pid.TD", cfg.PID.TD},
			{"KD", "pid.KD", cfg.PID.KD},
			{"SV", "pid.SV", cfg.PID.SV},
			{"MV", "pid.MV", cfg.PID.MV},
			{"MODE", "pid.MODE", float64(cfg.PID.MODE)},
			{"SWPN", "pid.SWPN", float64(cfg.PID.SWPN)},
			{"SVSCL", "pid.SVSCL", cfg.PID.SVSCL},
			{"SVSCH", "pid.SVSCH", cfg.PID.SVSCH},
			{"SVL", "pid.SVL", cfg.PID.SVL},
			{"SVH", "pid.SVH", cfg.PID.SVH},
			{"MVSCL", "pid.MVSCL", cfg.PID.MVSCL},
			{"MVSCH", "pid.MVSCH", cfg.PID.MVSCH},
			{"MVL", "pid.MVL", cfg.PID.MVL},
			{"MVH", "pid.MVH", cfg.PID.MVH},
		}
		for _, w := range pidFieldWrites {
			if !modified[w.path] {
				continue
			}
			setMappingFloat(paramsNode, w.key, w.val)
		}
		// PV 是运行时只读值，绝不写入；即使原 YAML 有 PV 也不动。
		// 不调用 setMappingFloat(paramsNode, "PV", ...)
	}

	return nil
}

func valveChanged(modified map[string]bool) bool {
	for k := range modified {
		if strings.HasPrefix(k, "valve.") {
			return true
		}
	}
	return false
}

func tankChanged(prefix string, modified map[string]bool) bool {
	for k := range modified {
		if strings.HasPrefix(k, prefix+".") {
			return true
		}
	}
	return false
}

func pidChanged(modified map[string]bool) bool {
	for k := range modified {
		if strings.HasPrefix(k, "pid.") {
			return true
		}
	}
	return false
}

// ---------- yaml.Node 工具函数 ----------

func topLevelMapping(node *yaml.Node) *yaml.Node {
	if node == nil {
		return nil
	}
	if node.Kind == yaml.DocumentNode && len(node.Content) > 0 {
		return node.Content[0]
	}
	if node.Kind == yaml.MappingNode {
		return node
	}
	return nil
}

func mappingValue(m *yaml.Node, key string) *yaml.Node {
	if m == nil || m.Kind != yaml.MappingNode {
		return nil
	}
	for i := 0; i+1 < len(m.Content); i += 2 {
		if m.Content[i].Value == key {
			return m.Content[i+1]
		}
	}
	return nil
}

func mappingStringValue(m *yaml.Node, key string) string {
	v := mappingValue(m, key)
	if v == nil || v.Kind != yaml.ScalarNode {
		return ""
	}
	return v.Value
}

func mappingFloatValue(m *yaml.Node, key string) float64 {
	v := mappingValue(m, key)
	if v == nil || v.Kind != yaml.ScalarNode {
		return 0
	}
	n, err := strconv.ParseFloat(v.Value, 64)
	if err != nil {
		return 0
	}
	return n
}

func mappingBoolValue(m *yaml.Node, key string) bool {
	v := mappingValue(m, key)
	if v == nil || v.Kind != yaml.ScalarNode {
		return false
	}
	b, err := strconv.ParseBool(v.Value)
	if err != nil {
		return false
	}
	return b
}

// lookupFloat 返回 (值, true) 仅在键存在且解析成功时。
// 与 mappingFloatValue 不同：缺键时返回 false 而不是 0，让调用方区分"显式 0"与"未设置"。
func lookupFloat(m *yaml.Node, key string) (float64, bool) {
	v := mappingValue(m, key)
	if v == nil || v.Kind != yaml.ScalarNode {
		return 0, false
	}
	n, err := strconv.ParseFloat(v.Value, 64)
	if err != nil {
		return 0, false
	}
	return n, true
}

func lookupString(m *yaml.Node, key string) (string, bool) {
	v := mappingValue(m, key)
	if v == nil || v.Kind != yaml.ScalarNode {
		return "", false
	}
	return v.Value, true
}

func setMappingFloat(m *yaml.Node, key string, val float64) {
	v := mappingValue(m, key)
	if v != nil {
		v.Value = formatFloat(val)
		v.Tag = "!!float"
		v.Style = 0
		return
	}
	m.Content = append(m.Content,
		&yaml.Node{Kind: yaml.ScalarNode, Tag: "!!str", Value: key},
		&yaml.Node{Kind: yaml.ScalarNode, Tag: "!!float", Value: formatFloat(val)},
	)
}

func setMappingString(m *yaml.Node, key, val string) {
	v := mappingValue(m, key)
	if v != nil {
		v.Value = val
		v.Tag = "!!str"
		v.Style = 0
		return
	}
	m.Content = append(m.Content,
		&yaml.Node{Kind: yaml.ScalarNode, Tag: "!!str", Value: key},
		&yaml.Node{Kind: yaml.ScalarNode, Tag: "!!str", Value: val},
	)
}

func ensureMapping(m *yaml.Node, key string) *yaml.Node {
	if v := mappingValue(m, key); v != nil {
		if v.Kind != yaml.MappingNode {
			return nil
		}
		return v
	}
	created := &yaml.Node{Kind: yaml.MappingNode, Tag: "!!map"}
	m.Content = append(m.Content,
		&yaml.Node{Kind: yaml.ScalarNode, Tag: "!!str", Value: key},
		created,
	)
	return created
}

func formatFloat(v float64) string {
	if v == math.Trunc(v) && !math.IsInf(v, 0) {
		return strconv.FormatInt(int64(v), 10)
	}
	return strconv.FormatFloat(v, 'g', -1, 64)
}

func hashBytes(b []byte) string {
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}

func shortHash(h string) string {
	if len(h) <= 12 {
		return h
	}
	return h[:12]
}

func isFinite(v float64) bool {
	return !math.IsNaN(v) && !math.IsInf(v, 0)
}

func mapsEqual(a, b map[string]string) bool {
	if len(a) != len(b) {
		return false
	}
	keys := make([]string, 0, len(a))
	for k := range a {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		if a[k] != b[k] {
			return false
		}
	}
	return true
}

// torricelliOutflow 与 tank1SteadyLevel 与前端 conversions.ts 等价，用于跨字段校验。
func torricelliOutflow(area, level float64) float64 {
	if area <= 0 || level <= 0 {
		return 0
	}
	return area * math.Sqrt(2*9.81*level)
}

func tank1SteadyLevel(requiredFlow, outletArea float64) float64 {
	if requiredFlow <= 0 || outletArea <= 0 {
		return 0
	}
	v := requiredFlow / outletArea
	return (v * v) / (2 * 9.81)
}

// SortedPatchKeys 仅用于测试断言与日志顺序。
func SortedPatchKeys(patches []TemplatePatch) []string {
	out := make([]string, len(patches))
	for i, p := range patches {
		out[i] = p.Path
	}
	sort.Strings(out)
	return out
}
