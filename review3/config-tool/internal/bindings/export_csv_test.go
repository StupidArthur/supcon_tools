/**
 * Go-side smoke tests for CSV export / temp cleanup helpers used by offline sim.
 */
package bindings_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"config-tool/internal/bindings"
)

func TestExportCSVRowsAndCleanupTempYAML(t *testing.T) {
	b := bindings.NewSystemBinding()

	dir, err := os.MkdirTemp("", "review3-draft-sim-*")
	if err != nil {
		t.Fatal(err)
	}
	yamlPath := filepath.Join(dir, "draft.yaml")
	if err := os.WriteFile(yamlPath, []byte("clock:\n  cycle_time: 0.5\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	out := filepath.Join(t.TempDir(), "out.csv")
	cols := []string{"_cycle", "x"}
	rows := []map[string]any{
		{"_cycle": 0, "x": 1.5},
		{"_cycle": 1, "x": 2.25},
	}
	if err := b.ExportCSVRows(cols, rows, out); err != nil {
		t.Fatalf("ExportCSVRows: %v", err)
	}
	raw, err := os.ReadFile(out)
	if err != nil {
		t.Fatal(err)
	}
	text := string(raw)
	if !strings.Contains(text, "_cycle,x") || !strings.Contains(text, "1.5") {
		t.Fatalf("unexpected csv: %q", text)
	}

	if err := b.CleanupTempYAML(yamlPath); err != nil {
		t.Fatalf("CleanupTempYAML: %v", err)
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatalf("temp dir should be removed, err=%v", err)
	}
}

func TestCleanupTempYAMLRejectsNonDraftDir(t *testing.T) {
	b := bindings.NewSystemBinding()
	dir := t.TempDir()
	path := filepath.Join(dir, "x.yaml")
	_ = os.WriteFile(path, []byte("a: 1\n"), 0o644)
	if err := b.CleanupTempYAML(path); err == nil {
		t.Fatal("expected reject non-draft dir")
	}
}
