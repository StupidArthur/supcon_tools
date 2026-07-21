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

var errorInterfaceType = reflect.TypeOf((*error)(nil)).Elem()

func projectRoot(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot resolve caller")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", ".."))
}

func assertResultFieldTypes(t *testing.T, resultType reflect.Type) {
	t.Helper()
	pathF, ok := resultType.FieldByName("Path")
	if !ok {
		t.Fatal("STAGE5-WRITEBACK-001: ApplyRuntimeOverridesResult missing field Path")
	}
	if pathF.Type.Kind() != reflect.String {
		t.Fatalf("STAGE5-WRITEBACK-001: Path must be string, got %s", pathF.Type)
	}
	hashF, ok := resultType.FieldByName("ContentHash")
	if !ok {
		t.Fatal("STAGE5-WRITEBACK-001: ApplyRuntimeOverridesResult missing field ContentHash")
	}
	if hashF.Type.Kind() != reflect.String {
		t.Fatalf("STAGE5-WRITEBACK-001: ContentHash must be string, got %s", hashF.Type)
	}
	af, ok := resultType.FieldByName("AppliedFields")
	if !ok {
		t.Fatal("STAGE5-WRITEBACK-001: ApplyRuntimeOverridesResult missing field AppliedFields")
	}
	if af.Type.Kind() != reflect.Slice || af.Type.Elem().Kind() != reflect.String {
		t.Fatalf("STAGE5-WRITEBACK-001: AppliedFields must be []string, got %s", af.Type)
	}
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
	assertField := func(name string, kind reflect.Kind) {
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
	}
	assertField("TargetPath", reflect.String)
	assertField("ExpectedHash", reflect.String)
	assertField("Overrides", reflect.Map)
	assertField("IncludeMV", reflect.Bool)

	out0 := mt.Out(0)
	if out0.Kind() == reflect.Ptr {
		out0 = out0.Elem()
	}
	if out0.Kind() != reflect.Struct {
		t.Fatalf("STAGE5-WRITEBACK-001: first return must be Result struct, got %s", out0.Kind())
	}
	assertResultFieldTypes(t, out0)

	// Second return must be exactly the error interface (safe for IsNil).
	if mt.Out(1) != errorInterfaceType {
		t.Fatalf(
			"STAGE5-WRITEBACK-001: second return must be exactly error interface, got %s",
			mt.Out(1),
		)
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
	errOut := outs[1]
	// Signature already requires exact error interface; only then IsNil is safe.
	if errOut.Type() != errorInterfaceType {
		t.Fatalf("STAGE5-WRITEBACK-001: second return type drifted from error: %s", errOut.Type())
	}
	if errOut.IsNil() {
		return result, nil
	}
	errObj, ok := errOut.Interface().(error)
	if !ok {
		t.Fatalf("STAGE5-WRITEBACK-001: second return is not error: %T", errOut.Interface())
	}
	return result, errObj
}

func resultStruct(t *testing.T, result reflect.Value) reflect.Value {
	t.Helper()
	if result.Kind() == reflect.Ptr {
		if result.IsNil() {
			t.Fatal("STAGE5-WRITEBACK-001: Result pointer must not be nil on success")
		}
		result = result.Elem()
	}
	if result.Kind() != reflect.Struct {
		t.Fatalf("STAGE5-WRITEBACK-001: Result must be struct, got %s", result.Kind())
	}
	return result
}

func appliedFields(t *testing.T, result reflect.Value) []string {
	t.Helper()
	res := resultStruct(t, result)
	f := res.FieldByName("AppliedFields")
	if !f.IsValid() || f.Kind() != reflect.Slice {
		t.Fatal("STAGE5-WRITEBACK-001: AppliedFields missing or not a slice")
	}
	applied, ok := f.Interface().([]string)
	if !ok {
		t.Fatalf("STAGE5-WRITEBACK-001: AppliedFields must be []string, got %T", f.Interface())
	}
	return applied
}

func containsField(applied []string, want string) bool {
	wantU := strings.ToUpper(want)
	for _, a := range applied {
		au := strings.ToUpper(a)
		if au == wantU || strings.HasSuffix(au, "."+wantU) {
			return true
		}
	}
	return false
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

func TestAcceptanceApplyRuntimeOverridesRejectsMVWhenIncludeMVFalse(t *testing.T) {
	// Real MV-in-request behavior: Overrides contains both SV and MV with IncludeMV=false.
	// Formal policy (SECOND_ORDER_TANK_ACCEPTANCE_SPEC §2.4): whole-batch reject; file unchanged.
	_, method := resolveApplyMethod(t)
	root := projectRoot(t)
	src := filepath.Join(root, "config", "单阀门二阶水箱.yaml")
	dst := filepath.Join(t.TempDir(), "mv_default_off.yaml")
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
		setStructField(t, req, "Overrides", map[string]float64{
			"SV": 0.61,
			"MV": 45.0,
		})
		setStructField(t, req, "IncludeMV", false)
	})
	_, callErr := callApply(t, method, arg)
	if callErr == nil {
		t.Fatal(
			"STAGE5-WRITEBACK-003: IncludeMV=false with MV in Overrides must reject the entire batch " +
				"(file must remain unchanged; silent ignore of MV is not allowed)",
		)
	}
	after, _ := os.ReadFile(dst)
	if string(after) != string(data) {
		t.Fatal("STAGE5-WRITEBACK-003: rejected MV batch must leave YAML completely unchanged")
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

	wantFields := map[string]float64{"PB": 22, "TI": 80, "SV": 0.75}
	arg := buildRequest(t, method, func(req reflect.Value) {
		setStructField(t, req, "TargetPath", dst)
		setStructField(t, req, "ExpectedHash", doc.ContentHash)
		setStructField(t, req, "Overrides", wantFields)
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

	res := resultStruct(t, result)
	pathV := res.FieldByName("Path")
	hashV := res.FieldByName("ContentHash")
	if pathV.Kind() != reflect.String || pathV.String() == "" {
		t.Fatal("STAGE5-WRITEBACK-001: Path must be non-empty string on success")
	}
	if hashV.Kind() != reflect.String || hashV.String() == "" {
		t.Fatal("STAGE5-WRITEBACK-001: ContentHash must be non-empty string on success")
	}

	applied := appliedFields(t, result)
	if len(applied) == 0 {
		t.Fatal("STAGE5-WRITEBACK-005: AppliedFields must be non-empty after successful whitelist save")
	}
	for name := range wantFields {
		if !containsField(applied, name) {
			t.Fatalf("STAGE5-WRITEBACK-005: AppliedFields must include written field %s; got %v", name, applied)
		}
	}
	for _, a := range applied {
		upper := strings.ToUpper(a)
		if upper == "MV" || strings.HasSuffix(upper, ".MV") {
			t.Fatalf("STAGE5-WRITEBACK-003: MV must not appear in AppliedFields when IncludeMV=false; applied=%v", applied)
		}
		if upper == "PV" || strings.HasSuffix(upper, ".PV") {
			t.Fatalf("STAGE5-WRITEBACK-003: PV must not appear in AppliedFields; applied=%v", applied)
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
