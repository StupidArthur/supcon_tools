package stage5_acceptance_test

// Prospective behavioral acceptance for TemplateConfigBinding.ApplyRuntimeOverrides.
// Reflect-safe: never panic; mismatched signatures → STAGE5-WRITEBACK-* failures.
// See SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md §2.4.

import (
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
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

// resolveApplyMethod returns the bound method value after validating the formal signature.
func resolveApplyMethod(t *testing.T) (binding *bindings.TemplateConfigBinding, method reflect.Value) {
	t.Helper()
	binding = bindings.NewTemplateConfigBinding()
	method = reflect.ValueOf(binding).MethodByName(applyRuntimeOverridesMethod)
	if !method.IsValid() {
		t.Fatalf(
			"STAGE5-WRITEBACK-001: public method TemplateConfigBinding.%s required "+
				"(SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md §2.4)",
			applyRuntimeOverridesMethod,
		)
	}
	mt := method.Type()
	if mt.NumIn() != 1 {
		t.Fatalf("STAGE5-WRITEBACK-001: %s must take exactly 1 argument (request DTO), NumIn=%d",
			applyRuntimeOverridesMethod, mt.NumIn())
	}
	if mt.NumOut() != 2 {
		t.Fatalf("STAGE5-WRITEBACK-001: %s must return (Result, error), NumOut=%d",
			applyRuntimeOverridesMethod, mt.NumOut())
	}
	reqType := mt.In(0)
	if reqType.Kind() == reflect.Ptr {
		reqType = reqType.Elem()
	}
	if reqType.Kind() != reflect.Struct {
		t.Fatalf("STAGE5-WRITEBACK-001: request parameter must be struct, got %s", reqType.Kind())
	}
	assertField := func(name string, kind reflect.Kind, assignableTo reflect.Type) {
		f, ok := reqType.FieldByName(name)
		if !ok {
			t.Fatalf("STAGE5-WRITEBACK-002: ApplyRuntimeOverridesRequest missing field %s", name)
		}
		ft := f.Type
		if kind == reflect.Map {
			if ft.Kind() != reflect.Map || ft.Key().Kind() != reflect.String || ft.Elem().Kind() != reflect.Float64 {
				t.Fatalf("STAGE5-WRITEBACK-002: field %s must be map[string]float64, got %s", name, ft)
			}
			return
		}
		if ft.Kind() != kind {
			t.Fatalf("STAGE5-WRITEBACK-002: field %s must be %s, got %s", name, kind, ft.Kind())
		}
		_ = assignableTo
	}
	assertField("TargetPath", reflect.String, nil)
	assertField("ExpectedHash", reflect.String, nil)
	assertField("Overrides", reflect.Map, nil)
	assertField("IncludeMV", reflect.Bool, nil)

	out0 := mt.Out(0)
	if out0.Kind() == reflect.Ptr {
		out0 = out0.Elem()
	}
	if out0.Kind() != reflect.Struct {
		t.Fatalf("STAGE5-WRITEBACK-001: first return must be Result struct, got %s", out0.Kind())
	}
	for _, name := range []string{"Path", "ContentHash", "AppliedFields"} {
		if _, ok := out0.FieldByName(name); !ok {
			t.Fatalf("STAGE5-WRITEBACK-001: ApplyRuntimeOverridesResult missing field %s", name)
		}
	}
	errType := mt.Out(1)
	if errType != reflect.TypeOf((*error)(nil)).Elem() {
		// Accept any type that implements error interface.
		if !errType.Implements(reflect.TypeOf((*error)(nil)).Elem()) && errType.Kind() != reflect.Interface {
			t.Fatalf("STAGE5-WRITEBACK-001: second return must implement error, got %s", errType)
		}
	}
	return binding, method
}

func buildRequest(t *testing.T, method reflect.Value, fill func(reflect.Value)) reflect.Value {
	t.Helper()
	inType := method.Type().In(0)
	if inType.Kind() == reflect.Ptr {
		ptr := reflect.New(inType.Elem())
		fill(ptr.Elem())
		return ptr
	}
	val := reflect.New(inType).Elem()
	fill(val)
	return val
}

func setStructField(t *testing.T, dest reflect.Value, name string, value any) {
	t.Helper()
	f := dest.FieldByName(name)
	if !f.IsValid() || !f.CanSet() {
		t.Fatalf("STAGE5-WRITEBACK-002: cannot set field %s", name)
	}
	v := reflect.ValueOf(value)
	if !v.Type().AssignableTo(f.Type()) {
		t.Fatalf("STAGE5-WRITEBACK-002: field %s type mismatch: have %s want %s",
			name, v.Type(), f.Type())
	}
	f.Set(v)
}

func callApply(t *testing.T, method reflect.Value, arg reflect.Value) (result reflect.Value, err error) {
	t.Helper()
	outs := method.Call([]reflect.Value{arg})
	if len(outs) != 2 {
		t.Fatalf("STAGE5-WRITEBACK-001: expected 2 return values, got %d", len(outs))
	}
	result = outs[0]
	if outs[1].IsNil() {
		return result, nil
	}
	errObj, ok := outs[1].Interface().(error)
	if !ok {
		t.Fatalf("STAGE5-WRITEBACK-001: second return is not error: %T", outs[1].Interface())
	}
	return result, errObj
}

func TestAcceptanceApplyRuntimeOverridesSignature(t *testing.T) {
	resolveApplyMethod(t)
}

func TestAcceptanceApplyRuntimeOverridesRejectsForbiddenFields(t *testing.T) {
	_, method := resolveApplyMethod(t)
	root := projectRoot(t)
	src := filepath.Join(root, "config", "单阀门二阶水箱.yaml")
	dst := filepath.Join(t.TempDir(), "override_target.yaml")
	data, err := os.ReadFile(src)
	if err != nil {
		t.Fatalf("read builtin fixture: %v", err)
	}
	if err := os.WriteFile(dst, data, 0o644); err != nil {
		t.Fatalf("copy target: %v", err)
	}
	doc, err := config.NewTemplateService().LoadTemplate(dst)
	if err != nil {
		t.Fatalf("load: %v", err)
	}

	arg := buildRequest(t, method, func(req reflect.Value) {
		setStructField(t, req, "TargetPath", dst)
		setStructField(t, req, "ExpectedHash", doc.ContentHash)
		setStructField(t, req, "Overrides", map[string]float64{
			"PV":                      1,
			"tank_2.level":            0.9,
			"valve_1.current_opening": 10,
		})
		setStructField(t, req, "IncludeMV", false)
	})
	_, callErr := callApply(t, method, arg)
	if callErr == nil {
		t.Fatal("STAGE5-WRITEBACK-003: PV/realtime level/valve opening must be rejected")
	}
	after, _ := os.ReadFile(dst)
	if string(after) != string(data) {
		t.Fatal("STAGE5-WRITEBACK-003: rejected writeback must not modify YAML on disk")
	}
}

func TestAcceptanceApplyRuntimeOverridesExpectedHashConflict(t *testing.T) {
	_, method := resolveApplyMethod(t)
	root := projectRoot(t)
	src := filepath.Join(root, "config", "单阀门二阶水箱.yaml")
	dst := filepath.Join(t.TempDir(), "hash.yaml")
	data, err := os.ReadFile(src)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(dst, data, 0o644); err != nil {
		t.Fatal(err)
	}
	arg := buildRequest(t, method, func(req reflect.Value) {
		setStructField(t, req, "TargetPath", dst)
		setStructField(t, req, "ExpectedHash", "not-the-real-hash")
		setStructField(t, req, "Overrides", map[string]float64{"PB": 22})
		setStructField(t, req, "IncludeMV", false)
	})
	_, callErr := callApply(t, method, arg)
	if callErr == nil {
		t.Fatal("STAGE5-WRITEBACK-004: ExpectedHash conflict must reject write")
	}
	after, _ := os.ReadFile(dst)
	if string(after) != string(data) {
		t.Fatal("STAGE5-WRITEBACK-004: hash conflict must leave file unchanged")
	}
}

func TestAcceptanceApplyRuntimeOverridesWhitelistSave(t *testing.T) {
	_, method := resolveApplyMethod(t)
	root := projectRoot(t)
	src := filepath.Join(root, "config", "单阀门二阶水箱.yaml")
	dst := filepath.Join(t.TempDir(), "ok.yaml")
	data, err := os.ReadFile(src)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(dst, data, 0o644); err != nil {
		t.Fatal(err)
	}
	doc, err := config.NewTemplateService().LoadTemplate(dst)
	if err != nil {
		t.Fatal(err)
	}

	arg := buildRequest(t, method, func(req reflect.Value) {
		setStructField(t, req, "TargetPath", dst)
		setStructField(t, req, "ExpectedHash", doc.ContentHash)
		setStructField(t, req, "Overrides", map[string]float64{"PB": 22, "TI": 80, "SV": 0.75})
		setStructField(t, req, "IncludeMV", false)
	})
	result, callErr := callApply(t, method, arg)
	if callErr != nil {
		t.Fatalf("STAGE5-WRITEBACK-004: whitelist save should succeed: %v", callErr)
	}
	after, err := os.ReadFile(dst)
	if err != nil {
		t.Fatal(err)
	}
	if string(after) == string(data) {
		t.Fatal("STAGE5-WRITEBACK-005: saved YAML must change when whitelist overrides apply")
	}
	if _, err := config.NewTemplateService().LoadTemplate(dst); err != nil {
		t.Fatalf("STAGE5-WRITEBACK-005: output YAML must remain loadable: %v", err)
	}
	// Result fields when struct value.
	resVal := result
	if resVal.Kind() == reflect.Ptr {
		resVal = resVal.Elem()
	}
	if f := resVal.FieldByName("AppliedFields"); f.IsValid() && f.Kind() == reflect.Slice && f.Len() > 0 {
		applied, ok := f.Interface().([]string)
		if !ok {
			t.Fatalf("STAGE5-WRITEBACK-001: AppliedFields must be []string, got %T", f.Interface())
		}
		for _, a := range applied {
			upper := strings.ToUpper(a)
			if upper == "MV" || strings.HasSuffix(upper, ".MV") {
				t.Fatalf("STAGE5-WRITEBACK-003: MV must not be written when IncludeMV=false; applied=%v", applied)
			}
			if upper == "PV" || strings.HasSuffix(upper, ".PV") {
				t.Fatalf("STAGE5-WRITEBACK-003: PV must not appear in AppliedFields; applied=%v", applied)
			}
		}
	}
}

func TestAcceptanceApplyRuntimeOverridesRejectsBuiltinPath(t *testing.T) {
	_, method := resolveApplyMethod(t)
	root := projectRoot(t)
	builtin := filepath.Join(root, "config", "单阀门二阶水箱.yaml")
	before, err := os.ReadFile(builtin)
	if err != nil {
		t.Fatal(err)
	}
	doc, err := config.NewTemplateService().LoadTemplate(builtin)
	if err != nil {
		t.Fatal(err)
	}
	arg := buildRequest(t, method, func(req reflect.Value) {
		setStructField(t, req, "TargetPath", builtin)
		setStructField(t, req, "ExpectedHash", doc.ContentHash)
		setStructField(t, req, "Overrides", map[string]float64{"PB": 33})
		setStructField(t, req, "IncludeMV", false)
	})
	_, callErr := callApply(t, method, arg)
	if callErr == nil {
		t.Fatal("STAGE5-WRITEBACK-005: must not directly overwrite the builtin template")
	}
	after, _ := os.ReadFile(builtin)
	if string(after) != string(before) {
		t.Fatal("STAGE5-WRITEBACK-005: builtin template bytes must be unchanged")
	}
}
