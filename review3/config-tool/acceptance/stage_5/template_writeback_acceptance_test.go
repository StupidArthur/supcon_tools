package stage5_acceptance_test

// Prospective behavioral acceptance for TemplateConfigBinding.ApplyRuntimeOverrides.
// Method absence → contract assertion failure (reflect), never a compile error.
// See CONTRACT_SURFACES.md → STAGE5-WRITEBACK.

import (
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"testing"

	"config-tool/internal/bindings"
	"config-tool/internal/config"
)

const applyRuntimeOverridesMethod = "ApplyRuntimeOverrides"

func projectRoot(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot resolve caller")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", ".."))
}

func requireApplyMethod(t *testing.T) reflect.Value {
	t.Helper()
	binding := bindings.NewTemplateConfigBinding()
	method := reflect.ValueOf(binding).MethodByName(applyRuntimeOverridesMethod)
	if !method.IsValid() {
		t.Fatalf(
			"STAGE5-WRITEBACK-001: public method TemplateConfigBinding.%s required "+
				"(registered in CONTRACT_SURFACES.md); internal writeback.go filename is not a completion criterion",
			applyRuntimeOverridesMethod,
		)
	}
	return method
}

func TestAcceptanceApplyRuntimeOverridesMethodExists(t *testing.T) {
	requireApplyMethod(t)
}

func TestAcceptanceApplyRuntimeOverridesWhitelistBehavior(t *testing.T) {
	method := requireApplyMethod(t)
	root := projectRoot(t)
	src := filepath.Join(root, "config", "单阀门二阶水箱.yaml")
	dstDir := t.TempDir()
	dst := filepath.Join(dstDir, "override_target.yaml")
	data, err := os.ReadFile(src)
	if err != nil {
		t.Fatalf("read builtin fixture: %v", err)
	}
	if err := os.WriteFile(dst, data, 0o644); err != nil {
		t.Fatalf("copy target: %v", err)
	}

	// Call signature is implementation-defined but must accept a request-like value.
	// We probe with a map-shaped request via a dedicated DTO if present; otherwise fail with contract ID.
	reqType := method.Type().In(0)
	req := reflect.New(reqType).Elem()
	setField := func(name string, value any) bool {
		f := req.FieldByName(name)
		if !f.IsValid() || !f.CanSet() {
			return false
		}
		v := reflect.ValueOf(value)
		if v.Type().AssignableTo(f.Type()) {
			f.Set(v)
			return true
		}
		if f.Kind() == reflect.String && v.Kind() == reflect.String {
			f.SetString(v.String())
			return true
		}
		return false
	}
	if !setField("TargetPath", dst) && !setField("Path", dst) {
		t.Fatal("STAGE5-WRITEBACK-002: request must expose TargetPath (or Path) for YAML writeback")
	}
	// Forbidden overrides must be rejected.
	_ = setField("Overrides", map[string]float64{
		"PV":                    1,
		"tank_2.level":          0.9,
		"valve_1.current_opening": 10,
	})
	_ = setField("IncludeMV", false)

	out := method.Call([]reflect.Value{req})
	if len(out) >= 1 {
		errVal := out[len(out)-1]
		if errVal.IsNil() {
			t.Fatal("STAGE5-WRITEBACK-003: PV/realtime level/valve opening must be rejected")
		}
	}

	after, _ := os.ReadFile(dst)
	if string(after) != string(data) {
		t.Fatal("STAGE5-WRITEBACK-003: rejected writeback must not modify YAML on disk")
	}
}

func TestAcceptanceApplyRuntimeOverridesWhitelistSaveAndParse(t *testing.T) {
	method := requireApplyMethod(t)
	root := projectRoot(t)
	src := filepath.Join(root, "config", "单阀门二阶水箱.yaml")
	dstDir := t.TempDir()
	dst := filepath.Join(dstDir, "ok.yaml")
	data, err := os.ReadFile(src)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	if err := os.WriteFile(dst, data, 0o644); err != nil {
		t.Fatalf("write: %v", err)
	}

	doc, err := config.NewTemplateService().LoadTemplate(dst)
	if err != nil {
		t.Fatalf("load template: %v", err)
	}

	reqType := method.Type().In(0)
	req := reflect.New(reqType).Elem()
	setString := func(name, value string) {
		f := req.FieldByName(name)
		if f.IsValid() && f.CanSet() && f.Kind() == reflect.String {
			f.SetString(value)
		}
	}
	setString("TargetPath", dst)
	setString("Path", dst)
	setString("ExpectedHash", doc.ContentHash)

	f := req.FieldByName("Overrides")
	if f.IsValid() && f.CanSet() {
		ov := map[string]float64{"PB": 22, "TI": 80, "SV": 0.75}
		f.Set(reflect.ValueOf(ov))
	} else {
		t.Fatal("STAGE5-WRITEBACK-002: request must accept whitelist Overrides map")
	}
	if mv := req.FieldByName("IncludeMV"); mv.IsValid() && mv.CanSet() && mv.Kind() == reflect.Bool {
		mv.SetBool(false)
	}

	out := method.Call([]reflect.Value{req})
	errVal := out[len(out)-1]
	if !errVal.IsNil() {
		t.Fatalf("STAGE5-WRITEBACK-004: whitelist save should succeed after revalidation: %v", errVal.Interface())
	}
	after, err := os.ReadFile(dst)
	if err != nil {
		t.Fatal(err)
	}
	if string(after) == string(data) {
		t.Fatal("STAGE5-WRITEBACK-005: saved YAML must change when whitelist overrides apply")
	}
	// Running identity must not be rewritten by writeback — verified by caller; here ensure file still loads.
	if _, err := config.NewTemplateService().LoadTemplate(dst); err != nil {
		t.Fatalf("STAGE5-WRITEBACK-005: output YAML must remain loadable: %v", err)
	}
}
