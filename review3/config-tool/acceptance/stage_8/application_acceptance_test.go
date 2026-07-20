package stage8_acceptance_test

// Prospective application-level acceptance for stage 8 E2E preflight.

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func projectRoot(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("caller")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", ".."))
}

func TestAcceptanceStage8ScenarioJSON(t *testing.T) {
	root := projectRoot(t)
	path := filepath.Join(root, "tools", "stage_verification", "fixtures", "e2e", "stage_8_scenario.json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("STAGE8-E2E-001: scenario fixture missing: %v", err)
	}
	var doc struct {
		Steps []struct {
			ID string `json:"id"`
		} `json:"steps"`
	}
	if err := json.Unmarshal(data, &doc); err != nil {
		t.Fatalf("invalid scenario json: %v", err)
	}
	if len(doc.Steps) != 29 {
		t.Fatalf("STAGE8-E2E: expected 29 steps, got %d", len(doc.Steps))
	}
	if doc.Steps[0].ID != "STAGE8-E2E-001" || doc.Steps[28].ID != "STAGE8-E2E-029" {
		t.Fatalf("STAGE8-E2E: step ids must span 001..029")
	}
}

func TestAcceptanceStage8BindingsStillExported(t *testing.T) {
	// Application shell must keep SystemBinding + TemplateConfigBinding constructible.
	root := projectRoot(t)
	for _, rel := range []string{
		filepath.Join("config-tool", "internal", "bindings", "system.go"),
		filepath.Join("config-tool", "internal", "bindings", "template_config.go"),
	} {
		if _, err := os.Stat(filepath.Join(root, rel)); err != nil {
			t.Fatalf("STAGE8 application binding source missing: %s", rel)
		}
	}
}

func TestAcceptanceStage8FullWorkflowNotYetGreen(t *testing.T) {
	t.Fatal(
		"STAGE8-E2E-002..025: full Wails+DataFactory+OPC UA workflow not yet available as a " +
			"single automated Go harness; Python/frontend acceptance owns step-level preflight",
	)
}
