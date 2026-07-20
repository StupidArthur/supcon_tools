package stage1_acceptance_test

// Reviewer-owned Go black-box acceptance for TemplateService (stage 1).

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"config-tool/internal/config"
)

const fixtureYAML = `# keep-this-comment
clock:
  mode: REALTIME
  cycle_time: 0.5
  experimental_flag: true

program:
  - name: source_flow
    type: Variable
    value: 0.0012
    undocumented_key: keep-me
    display_args: []

  - name: valve_1
    type: VALVE
    params:
      full_travel_time: 12.0
      initial_opening: 0.0
      mystery_param: 42
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
      PV: 0.10
      SV: 0.8
      MV: 0.0
    display_args:
      - "MV[100]"
      - "PV[1.2]"
      - "SV[1.2]"
      - "MODE"
    inputs:
      PV: tank_2.level
`

func writeFixture(t *testing.T, dir, name, body string) string {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatalf("write fixture: %v", err)
	}
	return path
}

func TestAcceptanceLoadModifySaveReloadPreservesSemantics(t *testing.T) {
	dir := t.TempDir()
	src := writeFixture(t, dir, "tank.yaml", fixtureYAML)
	svc := config.NewTemplateService()

	doc, err := svc.LoadTemplate(src)
	if err != nil {
		t.Fatalf("LoadTemplate: %v", err)
	}
	out := filepath.Join(dir, "saved.yaml")
	result, err := svc.SaveTemplate(config.SaveTemplateRequest{
		SourcePath:     src,
		TargetPath:     out,
		ExpectedHash:   doc.ContentHash,
		AllowOverwrite: true,
		Patches:        []config.TemplatePatch{{Path: "tank2.radius", Value: 0.18}},
	})
	if err != nil {
		t.Fatalf("SaveTemplate: %v", err)
	}
	reloaded, err := svc.LoadTemplate(result.NewPath)
	if err != nil {
		t.Fatalf("reload: %v", err)
	}
	if reloaded.Config.Tank2.Radius != 0.18 {
		t.Fatalf("radius not persisted: %v", reloaded.Config.Tank2.Radius)
	}
	raw := string(mustRead(t, result.NewPath))
	for _, needle := range []string{
		"keep-this-comment",
		"undocumented_key",
		"mystery_param",
		"execute_first: true",
		"display_args",
		"value: 0.0012",
	} {
		if !strings.Contains(raw, needle) {
			t.Fatalf("saved YAML missing preserved content %q", needle)
		}
	}
	if result.NewHash == "" {
		t.Fatal("SaveTemplate returned empty NewHash")
	}
	diskHash := hashFile(t, result.NewPath)
	if result.NewHash != diskHash {
		t.Fatalf("NewHash %s != disk hash %s", result.NewHash, diskHash)
	}
}

func TestAcceptanceWrongHashDoesNotWrite(t *testing.T) {
	dir := t.TempDir()
	src := writeFixture(t, dir, "tank.yaml", fixtureYAML)
	svc := config.NewTemplateService()
	doc, err := svc.LoadTemplate(src)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	before := mustRead(t, src)
	_, err = svc.SaveTemplate(config.SaveTemplateRequest{
		SourcePath:     src,
		TargetPath:     src,
		ExpectedHash:   "deadbeef",
		AllowOverwrite: true,
		Patches:        []config.TemplatePatch{{Path: "tank2.radius", Value: 0.2}},
	})
	if err == nil {
		t.Fatal("expected hash conflict error")
	}
	_ = doc
	after := mustRead(t, src)
	if string(before) != string(after) {
		t.Fatal("hash conflict must not rewrite source file")
	}
}

func TestAcceptanceUnicodePathRoundTrip(t *testing.T) {
	dir := t.TempDir()
	unicodeDir := filepath.Join(dir, "验收目录")
	if err := os.MkdirAll(unicodeDir, 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	src := writeFixture(t, unicodeDir, "二阶水箱.yaml", fixtureYAML)
	svc := config.NewTemplateService()
	doc, err := svc.LoadTemplate(src)
	if err != nil {
		t.Fatalf("load unicode: %v", err)
	}
	out := filepath.Join(unicodeDir, "另存.yaml")
	res, err := svc.SaveTemplate(config.SaveTemplateRequest{
		SourcePath:     src,
		TargetPath:     out,
		ExpectedHash:   doc.ContentHash,
		AllowOverwrite: true,
		Patches:        []config.TemplatePatch{{Path: "tank2.radius", Value: 0.16}},
	})
	if err != nil {
		t.Fatalf("save unicode: %v", err)
	}
	if _, err := svc.LoadTemplate(res.NewPath); err != nil {
		t.Fatalf("reload unicode: %v", err)
	}
}

func TestAcceptanceSavedYAMLParsesWithPythonDSLParser(t *testing.T) {
	dir := t.TempDir()
	src := writeFixture(t, dir, "tank.yaml", fixtureYAML)
	svc := config.NewTemplateService()
	doc, err := svc.LoadTemplate(src)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	out := filepath.Join(dir, "for_python.yaml")
	res, err := svc.SaveTemplate(config.SaveTemplateRequest{
		SourcePath:     src,
		TargetPath:     out,
		ExpectedHash:   doc.ContentHash,
		AllowOverwrite: true,
		Patches:        []config.TemplatePatch{{Path: "tank2.radius", Value: 0.17}},
	})
	if err != nil {
		t.Fatalf("save: %v", err)
	}
	projectRoot := filepath.Clean(filepath.Join("..", "..", ".."))
	cmd := exec.Command("python", "-c",
		"from controller.parser import DSLParser; "+
			"r=DSLParser().parse_file(r'"+res.NewPath+"'); "+
			"assert {p.name for p in r.program}=={'source_flow','valve_1','tank_1','tank_2','pid2'}")
	cmd.Dir = projectRoot
	output, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("python DSLParser failed: %v\n%s", err, output)
	}
}

func mustRead(t *testing.T, path string) []byte {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	return data
}

func hashFile(t *testing.T, path string) string {
	t.Helper()
	doc, err := config.NewTemplateService().LoadTemplate(path)
	if err != nil {
		t.Fatalf("hash via load: %v", err)
	}
	return doc.ContentHash
}
