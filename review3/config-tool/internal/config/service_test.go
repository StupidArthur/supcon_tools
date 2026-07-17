package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestExportImportRoundTrip(t *testing.T) {
	canvas := CanvasState{
		Clock: ClockConfig{Mode: "REALTIME", CycleTime: 0.5},
		Nodes: []BlockNode{
			{ID: "source_flow", Name: "source_flow", Type: "Variable", Position: Position{X: 0, Y: 0}, Params: map[string]any{"value": 0.18}},
			{ID: "valve_1", Name: "valve_1", Type: "VALVE", Position: Position{X: 250, Y: 0}, Params: map[string]any{"full_travel_time": 10.0}},
			{ID: "tank_1", Name: "tank_1", Type: "CYLINDRICAL_TANK", Position: Position{X: 500, Y: 0}, Params: map[string]any{}},
			{ID: "v_name", Name: "v_name", Type: "PID", Position: Position{X: 250, Y: 150}, Params: map[string]any{"PB": 12.0, "TI": 30.0, "TD": 0.15, "SV": 1.0}, ExecuteFirst: true},
		},
		Edges: []Connection{
			{ID: "e1", Source: "v_name", SourcePort: "MV", Target: "valve_1", TargetPort: "target_opening"},
			{ID: "e2", Source: "source_flow", SourcePort: "out", Target: "valve_1", TargetPort: "inlet_flow"},
			{ID: "e3", Source: "valve_1", SourcePort: "outlet_flow", Target: "tank_1", TargetPort: "inlet_flow"},
			{ID: "e4", Source: "tank_1", SourcePort: "level", Target: "v_name", TargetPort: "PV"},
		},
	}

	tmpDir := t.TempDir()
	yamlPath := filepath.Join(tmpDir, "test_export.yaml")

	service := NewService()
	if err := service.ExportYAML(canvas, yamlPath); err != nil {
		t.Fatalf("ExportYAML: %v", err)
	}

	data, err := os.ReadFile(yamlPath)
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	yamlStr := string(data)

	checks := []string{
		"mode: REALTIME",
		"cycle_time: 0.5",
		"name: source_flow",
		"type: Variable",
		"value: 0.18",
		"name: valve_1",
		"type: VALVE",
		"target_opening: v_name.MV",
		"inlet_flow: source_flow",
		"name: v_name",
		"type: PID",
		"execute_first: true",
		"PV: tank_1.level",
	}
	for _, check := range checks {
		if !strings.Contains(yamlStr, check) {
			t.Errorf("YAML missing: %q\nFull YAML:\n%s", check, yamlStr)
		}
	}

	if strings.Contains(yamlStr, "source_flow.out") {
		t.Error("YAML should not contain 'source_flow.out' for Variable type")
	}

	imported, err := service.ImportYAML(yamlPath)
	if err != nil {
		t.Fatalf("ImportYAML: %v", err)
	}
	if len(imported.Nodes) != 4 {
		t.Errorf("nodes: got %d, want 4", len(imported.Nodes))
	}
	if len(imported.Edges) != 4 {
		t.Errorf("edges: got %d, want 4", len(imported.Edges))
	}

	for _, edge := range imported.Edges {
		if edge.Source == "source_flow" && edge.SourcePort != "out" {
			t.Errorf("source_flow edge should have SourcePort='out', got %q", edge.SourcePort)
		}
	}

	result, err := service.Validate(canvas)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if !result.Valid {
		t.Errorf("Validate: expected valid, got errors: %v", result.Errors)
	}
}
