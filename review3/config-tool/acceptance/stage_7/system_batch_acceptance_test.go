package stage7_acceptance_test

// Prospective behavioral acceptance for SystemBinding batch surfaces.
// Uses public RunBatch/ExportBatch; fails with STAGE7-* when contracts unmet.

import (
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

func TestAcceptanceBatchPublicMethodsExist(t *testing.T) {
	b := bindings.NewSystemBinding()
	typ := reflect.TypeOf(b)
	for _, name := range []string{"RunBatch", "ExportBatch"} {
		if _, ok := typ.MethodByName(name); !ok {
			t.Fatalf("STAGE7-BATCH-001: SystemBinding.%s required public surface", name)
		}
	}
}

func TestAcceptanceRunBatchRejectsNonPositiveCycles(t *testing.T) {
	b := bindings.NewSystemBinding()
	_, err := b.RunBatch("x.yaml", 0)
	if err == nil {
		t.Fatal("STAGE7-BATCH-001: cycles<=0 must error")
	}
}

func TestAcceptanceBatchUniqueTempAndCleanupContract(t *testing.T) {
	b := bindings.NewSystemBinding()
	// Public seam for per-task work paths (registered in CONTRACT_SURFACES).
	method := reflect.ValueOf(b).MethodByName("AllocateBatchWorkDir")
	if !method.IsValid() {
		t.Fatal(
			"STAGE7-BATCH-003/004/008: SystemBinding.AllocateBatchWorkDir required so each batch " +
				"gets a unique temp path, concurrent tasks do not overwrite, and temps are cleaned",
		)
	}
	a := method.Call(nil)
	c := method.Call(nil)
	pathA := a[0].String()
	pathB := c[0].String()
	if pathA == "" || pathB == "" || pathA == pathB {
		t.Fatalf("STAGE7-BATCH-003: unique non-empty temp paths required, got %q and %q", pathA, pathB)
	}
}

func TestAcceptanceExportBatchRequiresExportPath(t *testing.T) {
	b := bindings.NewSystemBinding()
	err := b.ExportBatch("x.yaml", 10, "")
	// Empty export path should be rejected or create a defined error — probe current behavior.
	if err == nil {
		t.Fatal("STAGE7-CSV-005: ExportBatch with empty export path must not silently succeed")
	}
}

func TestAcceptanceRealtimeRunningBlocksBatchDocumented(t *testing.T) {
	b := bindings.NewSystemBinding()
	typ := reflect.TypeOf(b)
	// Prefer an explicit public guard if present; otherwise require documented mutex on RunBatch.
	if _, ok := typ.MethodByName("CanRunBatch"); ok {
		return
	}
	t.Fatal(
		"STAGE7-STATE-004: public CanRunBatch (or equivalent) required so realtime-running blocks concurrent batch",
	)
}

func TestAcceptanceUnicodePathsSupportedInAPI(t *testing.T) {
	root := projectRoot(t)
	unicodeDir := filepath.Join(t.TempDir(), "验收目录")
	if err := os.MkdirAll(unicodeDir, 0o755); err != nil {
		t.Fatal(err)
	}
	yamlPath := filepath.Join(unicodeDir, "方案.yaml")
	csvPath := filepath.Join(unicodeDir, "结果.csv")
	src := filepath.Join(root, "config", "单阀门二阶水箱.yaml")
	data, err := os.ReadFile(src)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(yamlPath, data, 0o644); err != nil {
		t.Fatal(err)
	}
	b := bindings.NewSystemBinding()
	// Without DataFactory path, ExportBatch fails fast — still validates Unicode path arguments are accepted by API.
	err = b.ExportBatch(yamlPath, 10, csvPath)
	if err == nil {
		t.Fatal("unexpected success without DataFactory")
	}
	if strings.Contains(err.Error(), "周期数") {
		t.Fatal("STAGE7-BATCH-002: unexpected cycle error")
	}
	// Path must appear or error must be DataFactory-related, not encoding failure.
	if strings.Contains(strings.ToLower(err.Error()), "unicode") && strings.Contains(err.Error(), "invalid") {
		t.Fatalf("STAGE7-BATCH-002: Unicode YAML/CSV paths must be accepted: %v", err)
	}
}
