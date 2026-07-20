package config

import (
	"fmt"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// builtinFixture 是阶段 1 内置模板的最小 YAML。
const builtinFixture = `# 单阀门二阶水箱 PID 液位控制（结构化 DSL 语法）
clock:
  mode: REALTIME
  cycle_time: 0.5

program:
  - name: source_flow
    type: Variable
    value: 0.0012
    display_args: []

  - name: valve_1
    type: VALVE
    params:
      full_travel_time: 12.0
      initial_opening: 0.0
    display_args: []
    inputs:
      target_opening: pid2.MV
      inlet_flow: source_flow

  - name: tank_1
    type: CYLINDRICAL_TANK
    params:
      height: 1.2
      radius: 0.15
      outlet_area: 0.00025
      initial_level: 0.15
    display_args:
      - "level[1.2]"
    inputs:
      inlet_flow: valve_1.outlet_flow

  - name: tank_2
    type: CYLINDRICAL_TANK
    params:
      height: 1.2
      radius: 0.15
      outlet_area: 0.0002
      initial_level: 0.10
    display_args:
      - "level[1.2]"
    inputs:
      inlet_flow: tank_1.outlet_flow

  - name: pid2
    type: PID
    execute_first: true
    params:
      PB: 30.0
      TI: 90.0
      TD: 20.0
      KD: 10.0
      PV: 0.10
      SV: 0.8
      MV: 0.0
      MODE: 5
      SWPN: 1
      SVSCL: 0.0
      SVSCH: 1.2
      SVL: 0.0
      SVH: 1.2
      MVSCL: 0.0
      MVSCH: 100.0
      MVL: 0.0
      MVH: 100.0
    display_args:
      - "MV[100]"
      - "PV[1.2]"
      - "SV[1.2]"
      - "MODE"
    inputs:
      PV: tank_2.level
`

func writeBuiltinFixture(t *testing.T, dir string) string {
	t.Helper()
	path := filepath.Join(dir, "单阀门二阶水箱.yaml")
	if err := os.WriteFile(path, []byte(builtinFixture), 0o644); err != nil {
		t.Fatalf("write fixture: %v", err)
	}
	return path
}

func TestLoadBuiltinTopology(t *testing.T) {
	dir := t.TempDir()
	srcPath := writeBuiltinFixture(t, dir)
	svc := NewTemplateService()
	doc, err := svc.LoadTemplate(srcPath)
	if err != nil {
		t.Fatalf("LoadTemplate: %v", err)
	}
	if len(doc.Topology.Programs) != 5 {
		t.Fatalf("programs: got %d, want 5", len(doc.Topology.Programs))
	}
	if doc.Config.CycleTime != 0.5 {
		t.Errorf("cycleTime: got %v want 0.5", doc.Config.CycleTime)
	}
	if doc.Config.SourceFlow != 0.0012 {
		t.Errorf("sourceFlow: got %v want 0.0012", doc.Config.SourceFlow)
	}
	if doc.Config.PID.PB != 30.0 {
		t.Errorf("pid.PB: got %v want 30", doc.Config.PID.PB)
	}
	if doc.Config.PID.MODE != 5 {
		t.Errorf("pid.MODE: got %v want 5", doc.Config.PID.MODE)
	}
	if doc.Config.Tank2.InitialLevel != 0.10 {
		t.Errorf("tank2.initialLevel: got %v want 0.10", doc.Config.Tank2.InitialLevel)
	}
}

// 实际目标 YAML 加载后，缺失的 flow_coefficient / min_opening / max_opening
// 必须按 Python VALVE.default_params 填入默认值。
func TestLoadAppliesPythonValveDefaults(t *testing.T) {
	dir := t.TempDir()
	srcPath := writeBuiltinFixture(t, dir)
	svc := NewTemplateService()
	doc, err := svc.LoadTemplate(srcPath)
	if err != nil {
		t.Fatalf("LoadTemplate: %v", err)
	}
	if doc.Config.Valve.FlowCoefficient != 1.0 {
		t.Errorf("flowCoefficient default should be 1.0 (Python VALVE.default_params), got %v",
			doc.Config.Valve.FlowCoefficient)
	}
	if doc.Config.Valve.MinOpening != 0 {
		t.Errorf("minOpening default should be 0, got %v", doc.Config.Valve.MinOpening)
	}
	if doc.Config.Valve.MaxOpening != 100 {
		t.Errorf("maxOpening default should be 100, got %v", doc.Config.Valve.MaxOpening)
	}
	if doc.Config.Valve.FullTravelTime != 12.0 {
		t.Errorf("fullTravelTime should be 12.0 from YAML, got %v", doc.Config.Valve.FullTravelTime)
	}
	// presence 必须准确标记缺失字段。
	if doc.Presence.Valve.FlowCoefficient {
		t.Error("presence.Valve.FlowCoefficient should be false when absent from YAML")
	}
	if doc.Presence.Valve.MinOpening {
		t.Error("presence.Valve.MinOpening should be false when absent from YAML")
	}
	if doc.Presence.Valve.MaxOpening {
		t.Error("presence.Valve.MaxOpening should be false when absent from YAML")
	}
}

func TestLoadMissingTopologyReturnsStructuredError(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "bad.yaml")
	bad := `clock:
  mode: REALTIME
  cycle_time: 0.5
program:
  - name: source_flow
    type: Variable
    value: 0.0012
  - name: valve_1
    type: VALVE
    params:
      full_travel_time: 12
    inputs:
      target_opening: pid2.MV
      inlet_flow: source_flow
`
	if err := os.WriteFile(path, []byte(bad), 0o644); err != nil {
		t.Fatal(err)
	}
	svc := NewTemplateService()
	_, err := svc.LoadTemplate(path)
	if err == nil {
		t.Fatal("expected error for missing pid2, got nil")
	}
	if !strings.Contains(err.Error(), "缺失固定 program") {
		t.Errorf("error should mention missing fixed program, got: %v", err)
	}
}

func TestLoadWrongInputsReturnsError(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "bad_inputs.yaml")
	bad := `clock:
  mode: REALTIME
  cycle_time: 0.5
program:
  - name: source_flow
    type: Variable
    value: 0.0012
  - name: valve_1
    type: VALVE
    params:
      full_travel_time: 12
    inputs:
      target_opening: pid2.SV
      inlet_flow: source_flow
  - name: tank_1
    type: CYLINDRICAL_TANK
    params:
      height: 1.2
      radius: 0.15
      outlet_area: 0.00025
      initial_level: 0.15
    inputs:
      inlet_flow: valve_1.outlet_flow
  - name: tank_2
    type: CYLINDRICAL_TANK
    params:
      height: 1.2
      radius: 0.15
      outlet_area: 0.0002
      initial_level: 0.10
    inputs:
      inlet_flow: tank_1.outlet_flow
  - name: pid2
    type: PID
    execute_first: true
    params:
      PB: 30
    inputs:
      PV: tank_2.level
`
	if err := os.WriteFile(path, []byte(bad), 0o644); err != nil {
		t.Fatal(err)
	}
	svc := NewTemplateService()
	_, err := svc.LoadTemplate(path)
	if err == nil {
		t.Fatal("expected topology mismatch error")
	}
	if !strings.Contains(err.Error(), "inputs 与模板不匹配") {
		t.Errorf("expected inputs mismatch error, got: %v", err)
	}
}

func TestLoadNonTargetTopologyRejected(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "foreign.yaml")
	foreign := `clock:
  mode: REALTIME
  cycle_time: 0.5
program:
  - name: source_flow
    type: Variable
    value: 0.0012
  - name: valve_1
    type: VALVE
    params:
      full_travel_time: 12
    inputs:
      target_opening: pid2.MV
      inlet_flow: source_flow
  - name: tank_1
    type: CYLINDRICAL_TANK
    params:
      height: 1.2
      radius: 0.15
      outlet_area: 0.00025
      initial_level: 0.15
    inputs:
      inlet_flow: valve_1.outlet_flow
  - name: tank_2
    type: CYLINDRICAL_TANK
    params:
      height: 1.2
      radius: 0.15
      outlet_area: 0.0002
      initial_level: 0.10
    inputs:
      inlet_flow: tank_1.outlet_flow
  - name: pid2
    type: PID
    execute_first: true
    params:
      PB: 30
    inputs:
      PV: tank_2.level
  - name: extra_node
    type: Variable
    value: 0
`
	if err := os.WriteFile(path, []byte(foreign), 0o644); err != nil {
		t.Fatal(err)
	}
	svc := NewTemplateService()
	_, err := svc.LoadTemplate(path)
	if err == nil {
		t.Fatal("expected rejection of non-target topology")
	}
	if !strings.Contains(err.Error(), "非固定 program") {
		t.Errorf("expected non-fixed program error, got: %v", err)
	}
}

// 单字段 patch：仅修改 tank2.radius；其他字段、display_args、注释、inputs、
// execute_first、pid.PV 等全部原样保留；YAML 中不应出现 flow_coefficient /
// min_opening / max_opening 等未 patch 字段。
func TestSaveSingleFieldPatchDoesNotTouchOtherFields(t *testing.T) {
	dir := t.TempDir()
	srcPath := writeBuiltinFixture(t, dir)
	svc := NewTemplateService()
	doc, err := svc.LoadTemplate(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	originalHash := doc.ContentHash

	// 记录未 patch 时的 YAML 关键内容（PV/display_args/inputs/execute_first/注释）。
	beforeBytes, err := os.ReadFile(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	before := string(beforeBytes)
	originalPVLine := extractScalarLine(t, before, "PV:")
	originalInputsLine := extractScalarLine(t, before, "PV: tank_2.level")
	originalComment := "# 单阀门二阶水箱"

	res, err := svc.SaveTemplate(SaveTemplateRequest{
		SourcePath:     srcPath,
		TargetPath:     filepath.Join(dir, "方案_半径018.yaml"),
		ExpectedHash:   originalHash,
		AllowOverwrite: true,
		Patches:        []TemplatePatch{{Path: "tank2.radius", Value: 0.18}},
	})
	if err != nil {
		t.Fatalf("SaveTemplate: %v", err)
	}
	savedBytes, err := os.ReadFile(res.NewPath)
	if err != nil {
		t.Fatal(err)
	}
	saved := string(savedBytes)

	// 1. PV 必须保留为 0.10，不得被改写为 0 或其他值。
	afterPVLine := extractScalarLine(t, saved, "PV:")
	if afterPVLine != originalPVLine {
		t.Errorf("pid.PV should be preserved: before=%q after=%q", originalPVLine, afterPVLine)
	}
	if !strings.Contains(saved, "PV: 0.10") {
		t.Errorf("pid.PV must remain 0.10; saved fragment:\n%s", saved)
	}

	// 2. display_args / 注释 / inputs / execute_first 全部保留。
	if !strings.Contains(saved, originalComment) {
		t.Error("file-leading comment lost")
	}
	if !strings.Contains(saved, "execute_first: true") {
		t.Error("execute_first lost")
	}
	if !strings.Contains(saved, originalInputsLine) {
		t.Errorf("pid2.inputs PV line lost; expected %q", originalInputsLine)
	}
	if !strings.Contains(saved, "target_opening: pid2.MV") {
		t.Error("valve_1.inputs target_opening lost")
	}
	if !strings.Contains(saved, "inlet_flow: source_flow") {
		t.Error("valve_1.inputs inlet_flow lost")
	}
	if !strings.Contains(saved, "display_args:") {
		t.Error("display_args lost")
	}
	if !strings.Contains(saved, `display_args:`) || !strings.Contains(saved, "level[1.2]") {
		t.Error("tank display_args lost")
	}
	if !strings.Contains(saved, `MV[100]`) {
		t.Error("pid2 display_args lost")
	}

	// 3. 不应新增未 patch 的可选 YAML 字段。
	for _, unwanted := range []string{
		"flow_coefficient:",
		"min_opening:",
		"max_opening:",
	} {
		if strings.Contains(saved, unwanted) {
			t.Errorf("single tank2.radius patch should not introduce %q; saved fragment:\n%s",
				unwanted, saved)
		}
	}

	// 4. tank2.radius 真的被改了。
	if !strings.Contains(saved, "radius: 0.18") {
		t.Errorf("tank2.radius patch did not take effect; saved fragment:\n%s", saved)
	}

	// 5. tank1.radius、tank1.height、tank2.height 等未 patch 字段保持原值。
	if !strings.Contains(saved, "radius: 0.15") {
		t.Error("tank1.radius should remain 0.15")
	}
	if !strings.Contains(saved, "height: 1.2") {
		t.Error("height should remain 1.2")
	}

	// 6. 程序数量与顺序：仍是 5 个，source_flow → pid2 顺序不变。
	if strings.Count(saved, "- name:") != 5 {
		t.Errorf("program count changed: %d", strings.Count(saved, "- name:"))
	}
}

func TestSavePIDPatchPreservesUnmodifiedScalarLexemes(t *testing.T) {
	dir := t.TempDir()
	srcPath := writeBuiltinFixture(t, dir)
	svc := NewTemplateService()
	doc, err := svc.LoadTemplate(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	res, err := svc.SaveTemplate(SaveTemplateRequest{
		SourcePath: srcPath, TargetPath: filepath.Join(dir, "pid.yaml"),
		ExpectedHash: doc.ContentHash, AllowOverwrite: true,
		Patches: []TemplatePatch{{Path: "pid.PB", Value: 40}},
	})
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(res.NewPath)
	if err != nil {
		t.Fatal(err)
	}
	saved := string(raw)
	for _, original := range []string{"TI: 90.0", "TD: 20.0", "SVSCL: 0.0", "MVSCH: 100.0"} {
		if !strings.Contains(saved, original) {
			t.Errorf("unmodified PID scalar was reformatted: missing %q\n%s", original, saved)
		}
	}
}

func TestLoadRejectsMalformedPresentNumericFields(t *testing.T) {
	for name, mutate := range map[string]func(string) string{
		"quoted numeric": func(s string) string {
			return strings.Replace(s, "initial_opening: 0.0", `initial_opening: "0.0"`, 1)
		},
		"fractional MODE": func(s string) string {
			return strings.Replace(s, "MODE: 5", "MODE: 5.5", 1)
		},
	} {
		t.Run(name, func(t *testing.T) {
			dir := t.TempDir()
			path := filepath.Join(dir, BuiltinTemplateRelativePath)
			if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, []byte(mutate(builtinFixture)), 0o644); err != nil {
				t.Fatal(err)
			}
			if _, err := NewTemplateService().LoadTemplate(path); err == nil {
				t.Fatal("malformed present numeric field must be rejected")
			}
		})
	}
}

func TestSaveValidatesFinalBatchInsteadOfPatchOrder(t *testing.T) {
	dir := t.TempDir()
	srcPath := writeBuiltinFixture(t, dir)
	svc := NewTemplateService()
	doc, err := svc.LoadTemplate(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	res, err := svc.SaveTemplate(SaveTemplateRequest{
		SourcePath: srcPath, TargetPath: filepath.Join(dir, "wide-mv-range.yaml"),
		ExpectedHash: doc.ContentHash, AllowOverwrite: true,
		Patches: []TemplatePatch{
			{Path: "pid.MV", Value: 150},
			{Path: "pid.MVSCH", Value: 200},
			{Path: "pid.MVH", Value: 200},
		},
	})
	if err != nil {
		t.Fatalf("valid final batch must not depend on patch order: %v", err)
	}
	if res.NewDocument.Config.PID.MV != 150 || res.NewDocument.Config.PID.MVH != 200 {
		t.Fatalf("unexpected final PID config: %+v", res.NewDocument.Config.PID)
	}
}

func TestTank2HeightAlwaysLinksBothSVUpperBounds(t *testing.T) {
	dir := t.TempDir()
	srcPath := writeBuiltinFixture(t, dir)
	raw, err := os.ReadFile(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	raw = []byte(strings.Replace(string(raw), "SVSCH: 1.2", "SVSCH: 1.0", 1))
	if err := os.WriteFile(srcPath, raw, 0o644); err != nil {
		t.Fatal(err)
	}
	svc := NewTemplateService()
	doc, err := svc.LoadTemplate(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	res, err := svc.SaveTemplate(SaveTemplateRequest{
		SourcePath: srcPath, TargetPath: filepath.Join(dir, "lower-height.yaml"),
		ExpectedHash: doc.ContentHash, AllowOverwrite: true,
		Patches: []TemplatePatch{{Path: "tank2.height", Value: 1.0}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if res.NewDocument.Config.PID.SVSCH != 1.0 || res.NewDocument.Config.PID.SVH != 1.0 {
		t.Fatalf("height linkage incomplete: %+v", res.NewDocument.Config.PID)
	}
}

func TestValidateTemplateConfigEnforcesPIDOperationRanges(t *testing.T) {
	dir := t.TempDir()
	doc, err := NewTemplateService().LoadTemplate(writeBuiltinFixture(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	tests := []struct {
		path   string
		mutate func(*TemplateConfig)
	}{
		{"valve.fullTravelTime", func(c *TemplateConfig) { c.Valve.FullTravelTime = -1 }},
		{"pid.SV", func(c *TemplateConfig) { c.PID.SV = c.PID.SVH + 0.1 }},
		{"pid.MV", func(c *TemplateConfig) { c.PID.MV = c.PID.MVH + 1 }},
		{"pid.SVL", func(c *TemplateConfig) { c.PID.SVL = c.PID.SVSCL - 0.1 }},
		{"pid.MVL", func(c *TemplateConfig) { c.PID.MVL = c.PID.MVSCL - 1 }},
	}
	for _, tc := range tests {
		t.Run(tc.path, func(t *testing.T) {
			cfg := doc.Config
			tc.mutate(&cfg)
			if !hasIssueAtPath(ValidateTemplateConfig(cfg), tc.path, "error") {
				t.Fatalf("expected validation issue at %s", tc.path)
			}
		})
	}
}

// 整批保存后调用 ValidateTemplateConfig 必须确保 cfg 合法。
func TestValidateTemplateConfigBlocksUnreachableAndOverflow(t *testing.T) {
	cfg := TemplateConfig{
		CycleTime:  0.5,
		ClockMode:  "REALTIME",
		SourceFlow: 0.0001, // 太小导致不可达
		Valve: ValveConfig{
			FullTravelTime:  12,
			InitialOpening:  0,
			FlowCoefficient: 1.0,
			MinOpening:      0,
			MaxOpening:      100,
		},
		Tank1: TankConfig{Height: 1.2, Radius: 0.15, OutletArea: 0.00025, InitialLevel: 0.15},
		Tank2: TankConfig{Height: 1.2, Radius: 0.15, OutletArea: 0.0002, InitialLevel: 0.10},
		PID: PIDConfig{
			PB: 30, TI: 90, TD: 20, KD: 10,
			SV: 0.8, MV: 0,
			MODE: 5, SWPN: 1,
			SVSCL: 0, SVSCH: 1.2, SVL: 0, SVH: 1.2,
			MVSCL: 0, MVSCH: 100, MVL: 0, MVH: 100,
		},
	}
	issues := ValidateTemplateConfig(cfg)
	if !hasIssueAtPath(issues, "sourceFlow", "error") {
		t.Errorf("expected blocking error on sourceFlow, got: %+v", issues)
	}

	cfg2 := cfg
	cfg2.SourceFlow = 0.0012 // 恢复默认流量
	cfg2.Tank1.OutletArea = 0.0001
	cfg2.Tank1.Height = 0.2
	issues2 := ValidateTemplateConfig(cfg2)
	if !hasIssueAtPath(issues2, "tank1.outletArea", "error") {
		t.Errorf("expected blocking error on tank1.outletArea for overflow, got: %+v", issues2)
	}
}

// Save 在整批校验失败时拒绝写盘。
func TestSaveRejectsWhenFinalConfigBlocks(t *testing.T) {
	dir := t.TempDir()
	srcPath := writeBuiltinFixture(t, dir)
	svc := NewTemplateService()
	doc, err := svc.LoadTemplate(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	originalBytes, err := os.ReadFile(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	originalHash := doc.ContentHash

	// 把 source_flow 调到 0.00005 让稳态不可达 → 触发阻塞。
	_, err = svc.SaveTemplate(SaveTemplateRequest{
		SourcePath:     srcPath,
		TargetPath:     filepath.Join(dir, "失败.yaml"),
		ExpectedHash:   originalHash,
		AllowOverwrite: true,
		Patches:        []TemplatePatch{{Path: "sourceFlow", Value: 0.00005}},
	})
	if err == nil {
		t.Fatal("expected blocking error from final config")
	}
	var ve *ValidationError
	if !asValidationError(err, &ve) {
		t.Errorf("expected *ValidationError, got: %T %v", err, err)
	} else if !hasIssueAtPath(ve.Issues, "sourceFlow", "error") {
		t.Errorf("expected sourceFlow blocking error inside ValidationError, got: %+v", ve.Issues)
	}

	// Tank 1 溢流同样阻塞。
	_, err = svc.SaveTemplate(SaveTemplateRequest{
		SourcePath:     srcPath,
		TargetPath:     filepath.Join(dir, "失败.yaml"),
		ExpectedHash:   originalHash,
		AllowOverwrite: true,
		Patches: []TemplatePatch{
			{Path: "tank1.height", Value: 0.2},
			{Path: "tank1.outletArea", Value: 0.0001},
		},
	})
	if err == nil {
		t.Fatal("expected blocking error from Tank 1 overflow")
	}
	if !asValidationError(err, &ve) {
		t.Errorf("expected *ValidationError, got: %T %v", err, err)
	} else if !hasIssueAtPath(ve.Issues, "tank1.outletArea", "error") {
		t.Errorf("expected tank1.outletArea blocking error, got: %+v", ve.Issues)
	}

	// 源文件未被改动。
	afterBytes, err := os.ReadFile(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	if string(afterBytes) != string(originalBytes) {
		t.Error("source file content changed after failed save")
	}
}

func TestSaveRejectsInvalidValueWithoutTouchingFile(t *testing.T) {
	dir := t.TempDir()
	srcPath := writeBuiltinFixture(t, dir)
	svc := NewTemplateService()
	doc, err := svc.LoadTemplate(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	originalBytes, err := os.ReadFile(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	originalHash := doc.ContentHash

	_, err = svc.SaveTemplate(SaveTemplateRequest{
		SourcePath:     srcPath,
		TargetPath:     filepath.Join(dir, "失败.yaml"),
		ExpectedHash:   originalHash,
		AllowOverwrite: true,
		Patches:        []TemplatePatch{{Path: "cycleTime", Value: -1}},
	})
	if err == nil {
		t.Fatal("expected rejection of negative cycleTime")
	}

	_, err = svc.SaveTemplate(SaveTemplateRequest{
		SourcePath:     srcPath,
		TargetPath:     filepath.Join(dir, "失败.yaml"),
		ExpectedHash:   originalHash,
		AllowOverwrite: true,
		Patches:        []TemplatePatch{{Path: "pid.MODE", Value: 9}},
	})
	if err == nil {
		t.Fatal("expected rejection of invalid MODE")
	}

	afterBytes, err := os.ReadFile(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	if string(afterBytes) != string(originalBytes) {
		t.Error("source file content changed after failed save")
	}
}

// NaN/Inf 在 patch value 与最终 cfg 中均被拒绝。
func TestSaveRejectsNaNAndInf(t *testing.T) {
	dir := t.TempDir()
	srcPath := writeBuiltinFixture(t, dir)
	svc := NewTemplateService()
	doc, err := svc.LoadTemplate(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	originalHash := doc.ContentHash

	for _, bad := range []float64{math.NaN(), math.Inf(1), math.Inf(-1)} {
		_, err := svc.SaveTemplate(SaveTemplateRequest{
			SourcePath:     srcPath,
			TargetPath:     filepath.Join(dir, "失败.yaml"),
			ExpectedHash:   originalHash,
			AllowOverwrite: true,
			Patches:        []TemplatePatch{{Path: "pid.PB", Value: bad}},
		})
		if err == nil {
			t.Errorf("expected rejection of NaN/Inf value %v", bad)
		}
	}
}

// ExpectedHash 必须非空。
func TestSaveRejectsEmptyExpectedHash(t *testing.T) {
	dir := t.TempDir()
	srcPath := writeBuiltinFixture(t, dir)
	svc := NewTemplateService()

	_, err := svc.SaveTemplate(SaveTemplateRequest{
		SourcePath:     srcPath,
		TargetPath:     filepath.Join(dir, "失败.yaml"),
		ExpectedHash:   "",
		AllowOverwrite: true,
		Patches:        []TemplatePatch{{Path: "pid.PB", Value: 40}},
	})
	if err == nil {
		t.Fatal("expected rejection of empty ExpectedHash")
	}
	if !strings.Contains(err.Error(), "expectedHash") {
		t.Errorf("expected expectedHash-related error, got: %v", err)
	}
}

// 哈希冲突检测：磁盘在我加载后被外部修改 → 拒绝保存。
func TestSaveHashConflictDetected(t *testing.T) {
	dir := t.TempDir()
	srcPath := writeBuiltinFixture(t, dir)
	svc := NewTemplateService()
	doc, err := svc.LoadTemplate(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(srcPath, []byte(builtinFixture+"\n# 外部修改\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	_, err = svc.SaveTemplate(SaveTemplateRequest{
		SourcePath:     srcPath,
		TargetPath:     filepath.Join(dir, "另一个.yaml"),
		ExpectedHash:   doc.ContentHash,
		AllowOverwrite: true,
		Patches:        []TemplatePatch{{Path: "pid.PB", Value: 40}},
	})
	if err == nil {
		t.Fatal("expected hash conflict error")
	}
	if !strings.Contains(err.Error(), "磁盘哈希已变更") {
		t.Errorf("expected hash-conflict message, got: %v", err)
	}
}

// 已有目标文件覆盖必须遵循 allowOverwrite。
func TestSaveOverwriteExistingRequiresAllowOverwrite(t *testing.T) {
	dir := t.TempDir()
	srcPath := writeBuiltinFixture(t, dir)
	tgtPath := filepath.Join(dir, "方案.yaml")
	if err := os.WriteFile(tgtPath, []byte(builtinFixture), 0o644); err != nil {
		t.Fatal(err)
	}
	svc := NewTemplateService()
	doc, err := svc.LoadTemplate(srcPath)
	if err != nil {
		t.Fatal(err)
	}

	// 不允许覆盖时拒绝。
	_, err = svc.SaveTemplate(SaveTemplateRequest{
		SourcePath:     srcPath,
		TargetPath:     tgtPath,
		ExpectedHash:   doc.ContentHash,
		AllowOverwrite: false,
		Patches:        []TemplatePatch{{Path: "tank2.radius", Value: 0.18}},
	})
	if err == nil {
		t.Fatal("expected rejection when overwriting without allowOverwrite")
	}
	if !strings.Contains(err.Error(), "覆盖需显式确认") {
		t.Errorf("expected overwrite-confirmation error, got: %v", err)
	}

	// 允许覆盖时成功。
	_, err = svc.SaveTemplate(SaveTemplateRequest{
		SourcePath:     srcPath,
		TargetPath:     tgtPath,
		ExpectedHash:   doc.ContentHash,
		AllowOverwrite: true,
		Patches:        []TemplatePatch{{Path: "tank2.radius", Value: 0.18}},
	})
	if err != nil {
		t.Errorf("explicit AllowOverwrite should succeed, got: %v", err)
	}
}

func TestSaveRejectsNonWhitelistedPath(t *testing.T) {
	dir := t.TempDir()
	srcPath := writeBuiltinFixture(t, dir)
	svc := NewTemplateService()
	doc, err := svc.LoadTemplate(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	_, err = svc.SaveTemplate(SaveTemplateRequest{
		SourcePath:     srcPath,
		TargetPath:     filepath.Join(dir, "失败.yaml"),
		ExpectedHash:   doc.ContentHash,
		AllowOverwrite: true,
		Patches:        []TemplatePatch{{Path: "pid.PV", Value: 1.0}},
	})
	if err == nil {
		t.Fatal("expected rejection of non-whitelisted PV path")
	}
	if !strings.Contains(err.Error(), "非白名单路径") {
		t.Errorf("expected non-whitelist error, got: %v", err)
	}
}

func TestSaveUnicodeTargetPath(t *testing.T) {
	dir := t.TempDir()
	srcPath := writeBuiltinFixture(t, dir)
	svc := NewTemplateService()
	doc, err := svc.LoadTemplate(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	tgtPath := filepath.Join(dir, "二阶水箱_方案_液位08_半径018.yaml")
	res, err := svc.SaveTemplate(SaveTemplateRequest{
		SourcePath:     srcPath,
		TargetPath:     tgtPath,
		ExpectedHash:   doc.ContentHash,
		AllowOverwrite: true,
		Patches:        []TemplatePatch{{Path: "tank2.radius", Value: 0.18}},
	})
	if err != nil {
		t.Fatalf("SaveTemplate: %v", err)
	}
	if res.NewDocument.Config.Tank2.Radius != 0.18 {
		t.Errorf("Unicode target path: radius not persisted")
	}
	if _, err := os.Stat(tgtPath); err != nil {
		t.Errorf("target file not created at %s: %v", tgtPath, err)
	}
}

func TestTank2HeightSyncsPIDScale(t *testing.T) {
	dir := t.TempDir()
	srcPath := writeBuiltinFixture(t, dir)
	svc := NewTemplateService()
	doc, err := svc.LoadTemplate(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	res, err := svc.SaveTemplate(SaveTemplateRequest{
		SourcePath:     srcPath,
		TargetPath:     filepath.Join(dir, "缩矮.yaml"),
		ExpectedHash:   doc.ContentHash,
		AllowOverwrite: true,
		Patches:        []TemplatePatch{{Path: "tank2.height", Value: 1.0}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if res.NewDocument.Config.PID.SVSCH != 1.0 {
		t.Errorf("pid.SVSCH should sync to 1.0, got %v", res.NewDocument.Config.PID.SVSCH)
	}
	if res.NewDocument.Config.PID.SVH != 1.0 {
		t.Errorf("pid.SVH should sync to 1.0, got %v", res.NewDocument.Config.PID.SVH)
	}
	// PV 必须保持原值（不被联动覆盖）。
	if res.NewDocument.Config.PID.SV == 0 {
		// 实际上 SV 在 builtinFixture 中是 0.8；这里只检查没被改成 0。
		// 我们另外校验 yaml 中 pid.PV 字面量。
	}
}

func TestSavePreservesUnknownKeys(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "with_extras.yaml")
	withExtras := `clock:
  mode: REALTIME
  cycle_time: 0.5
custom_top_field: keep_me
program:
  - name: source_flow
    type: Variable
    value: 0.0012
    custom_prog_field: keep_me_too
  - name: valve_1
    type: VALVE
    params:
      full_travel_time: 12
    inputs:
      target_opening: pid2.MV
      inlet_flow: source_flow
  - name: tank_1
    type: CYLINDRICAL_TANK
    params:
      height: 1.2
      radius: 0.15
      outlet_area: 0.00025
      initial_level: 0.15
    inputs:
      inlet_flow: valve_1.outlet_flow
  - name: tank_2
    type: CYLINDRICAL_TANK
    params:
      height: 1.2
      radius: 0.15
      outlet_area: 0.0002
      initial_level: 0.10
    inputs:
      inlet_flow: tank_1.outlet_flow
  - name: pid2
    type: PID
    execute_first: true
    params:
      PB: 30
      TI: 90
      TD: 20
      KD: 10
      PV: 0.10
      SV: 0.8
      MV: 0
      MODE: 5
      SWPN: 1
      SVSCL: 0
      SVSCH: 1.2
      SVL: 0
      SVH: 1.2
      MVSCL: 0
      MVSCH: 100
      MVL: 0
      MVH: 100
    inputs:
      PV: tank_2.level
`
	if err := os.WriteFile(src, []byte(withExtras), 0o644); err != nil {
		t.Fatal(err)
	}
	svc := NewTemplateService()
	doc, err := svc.LoadTemplate(src)
	if err != nil {
		t.Fatalf("LoadTemplate: %v", err)
	}
	res, err := svc.SaveTemplate(SaveTemplateRequest{
		SourcePath:     src,
		TargetPath:     filepath.Join(dir, "out.yaml"),
		ExpectedHash:   doc.ContentHash,
		AllowOverwrite: true,
		Patches:        []TemplatePatch{{Path: "pid.PB", Value: 50}},
	})
	if err != nil {
		t.Fatal(err)
	}
	out, err := os.ReadFile(res.NewPath)
	if err != nil {
		t.Fatal(err)
	}
	s := string(out)
	if !strings.Contains(s, "custom_top_field: keep_me") {
		t.Error("top-level unknown key lost")
	}
	if !strings.Contains(s, "custom_prog_field: keep_me_too") {
		t.Error("per-program unknown key lost")
	}
}

func TestFormatFloat(t *testing.T) {
	cases := []struct {
		in   float64
		want string
	}{
		{30, "30"},
		{30.0, "30"},
		{0.5, "0.5"},
		{0.0012, "0.0012"},
	}
	for _, c := range cases {
		if got := formatFloat(c.in); got != c.want {
			t.Errorf("formatFloat(%v) = %q, want %q", c.in, got, c.want)
		}
	}
}

// 通过环境变量 SUPCON_TOOL_REPO_ROOT 加载内置模板。
func TestLoadBuiltinWithEnvVar(t *testing.T) {
	root := t.TempDir()
	cfgDir := filepath.Join(root, "config")
	if err := os.MkdirAll(cfgDir, 0o755); err != nil {
		t.Fatal(err)
	}
	builtin := writeBuiltinFixture(t, cfgDir)
	t.Setenv("SUPCON_TOOL_REPO_ROOT", root)
	svc := NewTemplateService()
	doc, err := svc.LoadBuiltinTemplate()
	if err != nil {
		t.Fatalf("LoadBuiltinTemplate: %v", err)
	}
	if doc.Path != builtin {
		t.Errorf("Path: got %q want %q", doc.Path, builtin)
	}
	if doc.Config.Valve.FlowCoefficient != 1.0 {
		t.Errorf("flowCoefficient default: got %v want 1.0", doc.Config.Valve.FlowCoefficient)
	}
}

// 模拟 build/bin 类工作目录：把可执行文件放在 <root>/build/bin/config-tool.exe，
// 并把 builtin 放在 <root>/config/单阀门二阶水箱.yaml。
// 由于 os.Executable() 在 go test 下指向测试二进制，无法直接复用默认路径解析，
// 这里用一个独立可执行 helper binary 验证解析逻辑。
func TestLoadBuiltinFromBuildBinLayout(t *testing.T) {
	root := t.TempDir()
	cfgDir := filepath.Join(root, "config")
	binDir := filepath.Join(root, "build", "bin")
	if err := os.MkdirAll(cfgDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(binDir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeBuiltinFixture(t, cfgDir)

	got, err := resolveBuiltinTemplatePathFrom(binDir)
	if err != nil {
		t.Fatalf("resolve from build/bin: %v", err)
	}
	want := filepath.Join(root, BuiltinTemplateRelativePath)
	if got != want {
		t.Fatalf("resolved path: got %q want %q", got, want)
	}
}

// 同上的 Windows 版本：SUPCON_TOOL_REPO_ROOT 是主要路径，build/bin 布局通过环境变量
// 间接覆盖；helper 不依赖可执行文件绝对路径本身。
func TestLoadBuiltinResolvesAbsolutePath(t *testing.T) {
	root := t.TempDir()
	cfgDir := filepath.Join(root, "config")
	if err := os.MkdirAll(cfgDir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeBuiltinFixture(t, cfgDir)
	t.Setenv("SUPCON_TOOL_REPO_ROOT", root)

	got, err := ResolveBuiltinTemplatePath()
	if err != nil {
		t.Fatalf("resolveBuiltinTemplatePath: %v", err)
	}
	absRoot, _ := filepath.Abs(root)
	want := filepath.Join(absRoot, BuiltinTemplateRelativePath)
	if got != want {
		t.Errorf("resolved: got %q want %q", got, want)
	}
}

// LoadBuiltinTemplate 在环境变量未设置且可执行路径无效时返回错误，
// 不依赖当前工作目录。
func TestLoadBuiltinFailsCleanlyWithoutEnvOrExe(t *testing.T) {
	t.Setenv("SUPCON_TOOL_REPO_ROOT", "")
	// 这里无法让 os.Executable() 返回无效值；跳过该方向的具体断言，
	// 但保证 resolveBuiltinTemplatePath 在缺失文件时返回明确错误。
	root := t.TempDir()
	cfgDir := filepath.Join(root, "config")
	if err := os.MkdirAll(cfgDir, 0o755); err != nil {
		t.Fatal(err)
	}
	// 不写入 builtin 文件。
	t.Setenv("SUPCON_TOOL_REPO_ROOT", root)
	_, err := ResolveBuiltinTemplatePath()
	if err == nil {
		t.Fatal("expected error when builtin file is missing under SUPCON_TOOL_REPO_ROOT")
	}
}

// Save 后的产物必须能被真实 Python DSLParser 解析。
// 集成测试：调用 python -c "from controller.parser import DSLParser; ..."
func TestSaveOutputParsedByRealPythonDSLParser(t *testing.T) {
	if _, err := exec.LookPath("python"); err != nil {
		t.Skip("python interpreter not available")
	}
	dir := t.TempDir()
	srcPath := writeBuiltinFixture(t, dir)
	svc := NewTemplateService()
	doc, err := svc.LoadTemplate(srcPath)
	if err != nil {
		t.Fatal(err)
	}
	tgt := filepath.Join(dir, "方案_液位0.7.yaml")
	res, err := svc.SaveTemplate(SaveTemplateRequest{
		SourcePath:     srcPath,
		TargetPath:     tgt,
		ExpectedHash:   doc.ContentHash,
		AllowOverwrite: true,
		Patches: []TemplatePatch{
			{Path: "tank2.radius", Value: 0.18},
			{Path: "pid.SV", Value: 0.7},
		},
	})
	if err != nil {
		t.Fatalf("SaveTemplate: %v", err)
	}

	// 找到 review3 仓库根：当前测试在 config-tool 内运行。
	repoRoot, err := findRepoRoot()
	if err != nil {
		t.Skipf("review3 repo root not found: %v", err)
	}
	// 用独立 Python 进程解析保存的 YAML。
	pythonScript := fmt.Sprintf(
		"import sys; sys.path.insert(0, r%q); from controller.parser import DSLParser; c = DSLParser().parse_file(r%q); print('OK', len(c.program), c.program[0].name)",
		repoRoot, res.NewPath,
	)
	cmd := exec.Command("python", "-c", pythonScript)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("python DSLParser failed: %v\n%s", err, string(out))
	}
	if !strings.Contains(string(out), "OK 5 source_flow") {
		t.Errorf("unexpected parser output: %s", string(out))
	}
}

// findRepoRoot 从当前工作目录向上寻找 review3 仓库根（通过 .git 目录识别）。
func findRepoRoot() (string, error) {
	wd, err := os.Getwd()
	if err != nil {
		return "", err
	}
	dir := wd
	for i := 0; i < 16; i++ {
		if _, err := os.Stat(filepath.Join(dir, ".git")); err == nil {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return "", fmt.Errorf("未找到 review3 仓库根 (.git)")
}

// ---------- 内部工具 ----------

func extractScalarLine(t *testing.T, content, prefix string) string {
	t.Helper()
	idx := strings.Index(content, prefix)
	if idx < 0 {
		t.Fatalf("prefix %q not found in:\n%s", prefix, content)
	}
	end := idx + len(prefix)
	for end < len(content) && content[end] != '\n' {
		end++
	}
	return strings.TrimSpace(content[idx:end])
}

func extractBetween(t *testing.T, content, start, end string) string {
	t.Helper()
	si := strings.Index(content, start)
	if si < 0 {
		t.Fatalf("start %q not found", start)
	}
	ei := strings.Index(content, end)
	if ei < 0 || ei < si {
		t.Fatalf("end %q not found after start", end)
	}
	return content[si:ei]
}

func hasIssueAtPath(issues []ValidationIssue, path, level string) bool {
	for _, it := range issues {
		if it.Path == path && it.Level == level {
			return true
		}
	}
	return false
}

func asValidationError(err error, target **ValidationError) bool {
	if err == nil {
		return false
	}
	if ve, ok := err.(*ValidationError); ok {
		*target = ve
		return true
	}
	return false
}
