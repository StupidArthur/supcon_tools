package stage8_acceptance_test

// Prospective application-level acceptance for stage 8.
// Implementation-passable: no unconditional t.Fatal placeholders.

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"

	"config-tool/internal/bindings"
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

func TestAcceptanceStage8BindingsConstructible(t *testing.T) {
	sys := bindings.NewSystemBinding()
	_ = bindings.NewTemplateConfigBinding()
	_ = sys.Status()
	sys.Cleanup()
	sys.Cleanup() // repeatable / safe
	if sys.Status().Running {
		t.Fatal("STAGE8-E2E-027: Cleanup must leave Running=false")
	}
}

func TestAcceptanceStage8PublicMethodSurfaces(t *testing.T) {
	sys := bindings.NewSystemBinding()
	st := reflect.TypeOf(sys)
	for _, name := range []string{"Start", "Stop", "Status", "Cleanup", "RunBatch", "ExportBatch"} {
		if _, ok := st.MethodByName(name); !ok {
			t.Fatalf("STAGE8-E2E: SystemBinding.%s required", name)
		}
	}
	tpl := bindings.NewTemplateConfigBinding()
	method := reflect.ValueOf(tpl).MethodByName("ApplyRuntimeOverrides")
	if !method.IsValid() {
		t.Fatal(
			"STAGE8-E2E-019: TemplateConfigBinding.ApplyRuntimeOverrides required " +
				"(formal DTO in SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md §2.4)",
		)
	}
}

func TestAcceptanceStage8WailsBindingsRegistered(t *testing.T) {
	root := projectRoot(t)
	mainGo := filepath.Join(root, "config-tool", "main.go")
	data, err := os.ReadFile(mainGo)
	if err != nil {
		t.Fatalf("STAGE8-E2E: config-tool/main.go required: %v", err)
	}
	text := string(data)
	for _, needle := range []string{"SystemBinding", "TemplateConfigBinding"} {
		if !strings.Contains(text, needle) {
			t.Fatalf("STAGE8-E2E: Wails Bind list must include %s in main.go", needle)
		}
	}
}
