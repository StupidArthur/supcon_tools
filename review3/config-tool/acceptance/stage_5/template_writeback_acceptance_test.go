package stage5_acceptance_test

// Prospective reviewer acceptance for DSL writeback contracts (stage 5).
// Do not import missing Go symbols — probe files and existing public surfaces.

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func projectRoot(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot resolve caller path")
	}
	// .../config-tool/acceptance/stage_5/this_file.go → review3
	dir := filepath.Dir(file)
	return filepath.Clean(filepath.Join(dir, "..", "..", ".."))
}

func TestAcceptanceWritebackModuleFileExists(t *testing.T) {
	root := projectRoot(t)
	candidates := []string{
		filepath.Join(root, "config-tool", "internal", "templates", "writeback.go"),
		filepath.Join(root, "config-tool", "internal", "bindings", "writeback.go"),
		filepath.Join(root, "config-tool", "internal", "config", "writeback.go"),
	}
	for _, path := range candidates {
		if _, err := os.Stat(path); err == nil {
			return
		}
	}
	t.Fatalf(
		"STAGE5-WRITEBACK-001: expected writeback module file among %v "+
			"(runtimeOverrides must be separable from draft)",
		candidates,
	)
}

func TestAcceptanceWritebackWhitelistContractDocumentedInSource(t *testing.T) {
	root := projectRoot(t)
	searchRoots := []string{
		filepath.Join(root, "config-tool", "internal"),
	}
	needles := []string{
		"runtimeOverrides",
		"WritebackWhitelist",
		"SaveRuntimeOverrides",
	}
	foundAny := false
	_ = filepath.Walk(searchRoots[0], func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() || !strings.HasSuffix(path, ".go") {
			return nil
		}
		data, readErr := os.ReadFile(path)
		if readErr != nil {
			return nil
		}
		text := string(data)
		for _, needle := range needles {
			if strings.Contains(text, needle) {
				foundAny = true
			}
		}
		return nil
	})
	if !foundAny {
		t.Fatalf(
			"STAGE5-WRITEBACK-002: no writeback surface found (need runtimeOverrides / "+
				"WritebackWhitelist / SaveRuntimeOverrides); online writes must not mutate draft",
		)
	}
}

func TestAcceptanceWritebackForbiddenFieldsContract(t *testing.T) {
	root := projectRoot(t)
	var hit string
	_ = filepath.Walk(filepath.Join(root, "config-tool", "internal"), func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() || !strings.HasSuffix(path, ".go") {
			return nil
		}
		data, readErr := os.ReadFile(path)
		if readErr != nil {
			return nil
		}
		text := string(data)
		if strings.Contains(text, "WritebackForbidden") ||
			(strings.Contains(text, "writeback") && strings.Contains(text, "PV") &&
				strings.Contains(text, "current_opening")) {
			hit = path
		}
		return nil
	})
	if hit == "" {
		t.Fatalf(
			"STAGE5-WRITEBACK-003: writeback must declare forbidden fields "+
				"(PV, realtime level, realtime valve opening); MV must default to no writeback",
		)
	}
}

func TestAcceptanceWritebackRevalidatesBeforeSave(t *testing.T) {
	root := projectRoot(t)
	var hit string
	_ = filepath.Walk(filepath.Join(root, "config-tool", "internal"), func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() || !strings.HasSuffix(path, ".go") {
			return nil
		}
		data, readErr := os.ReadFile(path)
		if readErr != nil {
			return nil
		}
		text := string(data)
		if strings.Contains(text, "ValidateBeforeWriteback") ||
			strings.Contains(text, "RevalidateWriteback") ||
			(strings.Contains(text, "Writeback") && strings.Contains(text, "Validate")) {
			hit = path
		}
		return nil
	})
	if hit == "" {
		t.Fatalf(
			"STAGE5-WRITEBACK-004: writeback must re-validate before saving whitelist fields to DSL",
		)
	}
}

func TestAcceptanceSavedVsRunningDiffRemainsVisible(t *testing.T) {
	root := projectRoot(t)
	var hit string
	_ = filepath.Walk(filepath.Join(root, "config-tool"), func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return nil
		}
		base := filepath.Base(path)
		if base != "writeback.go" && base != "writeback_test.go" &&
			!strings.Contains(base, "Writeback") {
			return nil
		}
		data, readErr := os.ReadFile(path)
		if readErr != nil {
			return nil
		}
		text := string(data)
		if strings.Contains(text, "saved") && strings.Contains(text, "running") &&
			(strings.Contains(text, "Diff") || strings.Contains(text, "diff")) {
			hit = path
		}
		return nil
	})
	if hit == "" {
		t.Fatalf(
			"STAGE5-WRITEBACK-005: after writeback save, saved vs running differences must remain identifiable",
		)
	}
}
