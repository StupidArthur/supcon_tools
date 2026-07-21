package stage7_acceptance_test

// Prospective behavioral acceptance for SystemBinding batch surfaces.
// Public entry only: RunBatch / ExportBatch / Start / Stop / Status.
// See SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md §4.

import (
	"encoding/csv"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"config-tool/internal/bindings"
)

func copyBuiltinYAML(t *testing.T, dst string) {
	t.Helper()
	src := filepath.Join(projectRoot(t), "config", "单阀门二阶水箱.yaml")
	data, err := os.ReadFile(src)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(dst, data, 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestAcceptanceBatchPublicMethodsExist(t *testing.T) {
	b := bindings.NewSystemBinding()
	typ := reflect.TypeOf(b)
	for _, name := range []string{"RunBatch", "ExportBatch", "Start", "Stop", "Status"} {
		if _, ok := typ.MethodByName(name); !ok {
			t.Fatalf("STAGE7-BATCH-001: SystemBinding.%s required public surface", name)
		}
	}
}

func TestAcceptanceRunBatchRejectsNonPositiveCycles(t *testing.T) {
	b := bindings.NewSystemBinding()
	work := t.TempDir()
	wireFakeDataFactory(t, b, work)
	_, err := b.RunBatch("x.yaml", 0)
	if err == nil {
		t.Fatal("STAGE7-BATCH-001: cycles<=0 must error")
	}
}

func TestAcceptanceExportBatchRequiresExportPath(t *testing.T) {
	b := bindings.NewSystemBinding()
	work := t.TempDir()
	wireFakeDataFactory(t, b, work)
	yamlPath := filepath.Join(work, "cfg.yaml")
	copyBuiltinYAML(t, yamlPath)
	err := b.ExportBatch(yamlPath, 10, "")
	if err == nil {
		t.Fatal("STAGE7-CSV-005: ExportBatch with empty export path must not silently succeed")
	}
}

func TestAcceptanceUnicodePathsSupportedInAPI(t *testing.T) {
	b := bindings.NewSystemBinding()
	work := t.TempDir()
	wireFakeDataFactory(t, b, work)
	unicodeDir := filepath.Join(work, "验收目录")
	yamlPath := filepath.Join(unicodeDir, "方案.yaml")
	csvPath := filepath.Join(unicodeDir, "结果.csv")
	copyBuiltinYAML(t, yamlPath)
	if err := b.ExportBatch(yamlPath, 5, csvPath); err != nil {
		t.Fatalf("STAGE7-BATCH-002: Unicode YAML/CSV paths must succeed with fake DF: %v", err)
	}
	if _, err := os.Stat(csvPath); err != nil {
		t.Fatalf("STAGE7-BATCH-002: CSV not written at Unicode path: %v", err)
	}
}

func TestAcceptanceConcurrentRunBatchIsolation(t *testing.T) {
	// External proof: two concurrent RunBatch calls must not overwrite each other.
	// Current business uses shared `_batch_export.csv` — this test must surface that.
	b := bindings.NewSystemBinding()
	work := t.TempDir()
	wireFakeDataFactory(t, b, work)

	yamlA := filepath.Join(work, "task_a.yaml")
	yamlB := filepath.Join(work, "task_b.yaml")
	copyBuiltinYAML(t, yamlA)
	copyBuiltinYAML(t, yamlB)

	t.Setenv("FAKE_DF_SLEEP_S", "0.25")
	defer t.Setenv("FAKE_DF_SLEEP_S", "0")

	var (
		resA, resB bindings.BatchResult
		errA, errB error
		wg         sync.WaitGroup
	)
	wg.Add(2)
	go func() {
		defer wg.Done()
		resA, errA = b.RunBatch(yamlA, 8)
	}()
	go func() {
		defer wg.Done()
		resB, errB = b.RunBatch(yamlB, 8)
	}()
	wg.Wait()

	if errA != nil {
		t.Fatalf("STAGE7-BATCH-003: RunBatch A failed: %v", errA)
	}
	if errB != nil {
		t.Fatalf("STAGE7-BATCH-003: RunBatch B failed: %v", errB)
	}
	textA := batchMarker(resA)
	textB := batchMarker(resB)
	if textA == "" || textB == "" {
		t.Fatalf("STAGE7-BATCH-003: markers missing A=%q B=%q", textA, textB)
	}
	if textA == textB {
		t.Fatalf(
			"STAGE7-BATCH-003/004: concurrent RunBatch results collided "+
				"(shared temp CSV suspected). A=%q B=%q",
			textA, textB,
		)
	}
	if strings.Contains(textA, "task_b") || strings.Contains(textB, "task_a") {
		t.Fatalf("STAGE7-BATCH-004: cross-contamination A=%q B=%q", textA, textB)
	}
}

func TestAcceptanceConcurrentExportBatchIsolation(t *testing.T) {
	b := bindings.NewSystemBinding()
	work := t.TempDir()
	wireFakeDataFactory(t, b, work)
	yamlA := filepath.Join(work, "export_a.yaml")
	yamlB := filepath.Join(work, "export_b.yaml")
	outA := filepath.Join(work, "out_a.csv")
	outB := filepath.Join(work, "out_b.csv")
	copyBuiltinYAML(t, yamlA)
	copyBuiltinYAML(t, yamlB)

	var errA, errB error
	var wg sync.WaitGroup
	wg.Add(2)
	go func() {
		defer wg.Done()
		errA = b.ExportBatch(yamlA, 6, outA)
	}()
	go func() {
		defer wg.Done()
		errB = b.ExportBatch(yamlB, 6, outB)
	}()
	wg.Wait()
	if errA != nil || errB != nil {
		t.Fatalf("STAGE7-BATCH-003: ExportBatch concurrent failed: %v / %v", errA, errB)
	}
	a := readCSVMarkers(t, outA)
	c := readCSVMarkers(t, outB)
	if len(a) == 0 || len(c) == 0 {
		t.Fatal("STAGE7-BATCH-004: empty concurrent export")
	}
	if a[0] != "export_a.yaml" || c[0] != "export_b.yaml" {
		t.Fatalf("STAGE7-BATCH-004: A=%v B=%v", a, c)
	}
}

func TestAcceptanceOneFailureDoesNotBreakSiblingExport(t *testing.T) {
	b := bindings.NewSystemBinding()
	work := t.TempDir()
	wireFakeDataFactory(t, b, work)
	yamlOK := filepath.Join(work, "ok.yaml")
	yamlBad := filepath.Join(work, "bad.yaml")
	outOK := filepath.Join(work, "ok.csv")
	outBad := filepath.Join(work, "bad.csv")
	copyBuiltinYAML(t, yamlOK)
	copyBuiltinYAML(t, yamlBad)

	t.Setenv("FAKE_DF_EXIT", "0")
	if err := b.ExportBatch(yamlOK, 4, outOK); err != nil {
		t.Fatalf("setup ok export: %v", err)
	}
	t.Setenv("FAKE_DF_EXIT", "7")
	t.Setenv("FAKE_DF_STDERR", "engine boom")
	errBad := b.ExportBatch(yamlBad, 4, outBad)
	if errBad == nil {
		t.Fatal("STAGE7-BATCH-005: non-zero exit must fail ExportBatch")
	}
	t.Setenv("FAKE_DF_EXIT", "0")
	t.Setenv("FAKE_DF_STDERR", "")
	outOK2 := filepath.Join(work, "ok2.csv")
	if err := b.ExportBatch(yamlOK, 4, outOK2); err != nil {
		t.Fatalf("STAGE7-BATCH-005: sibling after failure must still work: %v", err)
	}
}

func TestAcceptanceExitCodeAndStderrPropagate(t *testing.T) {
	b := bindings.NewSystemBinding()
	work := t.TempDir()
	wireFakeDataFactory(t, b, work)
	yamlPath := filepath.Join(work, "cfg.yaml")
	copyBuiltinYAML(t, yamlPath)
	out := filepath.Join(work, "out.csv")
	t.Setenv("FAKE_DF_EXIT", "9")
	t.Setenv("FAKE_DF_STDERR", "stderr-marker-xyz")
	err := b.ExportBatch(yamlPath, 3, out)
	if err == nil {
		t.Fatal("STAGE7-BATCH-005: exit code must propagate as error")
	}
	if !strings.Contains(err.Error(), "stderr-marker-xyz") {
		t.Fatalf("STAGE7-BATCH-006: stderr must propagate into error: %v", err)
	}
}

func TestAcceptanceEmptyOutputMustNotSucceed(t *testing.T) {
	b := bindings.NewSystemBinding()
	work := t.TempDir()
	wireFakeDataFactory(t, b, work)
	yamlPath := filepath.Join(work, "cfg.yaml")
	copyBuiltinYAML(t, yamlPath)
	t.Setenv("FAKE_DF_EMPTY", "1")
	defer t.Setenv("FAKE_DF_EMPTY", "")
	res, err := b.RunBatch(yamlPath, 5)
	if err == nil && len(res.Rows) == 0 {
		t.Fatal("STAGE7-BATCH-007: empty batch output must not be treated as success")
	}
	if err == nil && len(res.Rows) > 0 {
		t.Fatal("STAGE7-BATCH-007: FAKE_DF_EMPTY must not produce data rows")
	}
}

func TestAcceptanceTempCleanupAfterRunBatch(t *testing.T) {
	b := bindings.NewSystemBinding()
	work := t.TempDir()
	wireFakeDataFactory(t, b, work)
	yamlPath := filepath.Join(work, "cfg.yaml")
	copyBuiltinYAML(t, yamlPath)
	shared := filepath.Join(work, "_batch_export.csv")
	_, err := b.RunBatch(yamlPath, 4)
	if err != nil {
		// May fail on empty-policy; still check cleanup of shared temp if created.
		_ = err
	}
	if _, statErr := os.Stat(shared); statErr == nil {
		t.Fatal("STAGE7-BATCH-008: shared _batch_export.csv must be removed after RunBatch")
	}
}

func TestAcceptanceRealtimeRunningBlocksBatch(t *testing.T) {
	b := bindings.NewSystemBinding()
	work := t.TempDir()
	wireFakeDataFactory(t, b, work)
	yamlPath := filepath.Join(work, "live.yaml")
	copyBuiltinYAML(t, yamlPath)

	t.Setenv("FAKE_DF_MODE", "realtime")
	startErr := b.Start(bindings.StartParams{
		ConfigPath:  yamlPath,
		Mode:        "REALTIME",
		CycleTime:   0.5,
		Port:        19001,
		APIPort:     18001,
		APIHost:     "127.0.0.1",
		RuntimeName: "acceptance_runtime",
		EnableOpcUa: false,
	})
	t.Setenv("FAKE_DF_MODE", "batch")
	if startErr != nil {
		t.Fatalf("STAGE7-STATE-004 setup Start: %v", startErr)
	}
	defer func() {
		_ = b.Stop()
		b.Cleanup()
	}()

	deadline := time.Now().Add(2 * time.Second)
	for !b.Status().Running && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if !b.Status().Running {
		t.Fatal("STAGE7-STATE-004 setup: Status.Running should be true after Start")
	}

	_, batchErr := b.RunBatch(yamlPath, 3)
	if batchErr == nil {
		t.Fatal("STAGE7-STATE-004: RunBatch must error while Status.Running=true (no second DataFactory)")
	}
	exportErr := b.ExportBatch(yamlPath, 3, filepath.Join(work, "blocked.csv"))
	if exportErr == nil {
		t.Fatal("STAGE7-STATE-004: ExportBatch must error while Status.Running=true")
	}

	if err := b.Stop(); err != nil {
		t.Fatalf("Stop: %v", err)
	}
	deadline = time.Now().Add(2 * time.Second)
	for b.Status().Running && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	t.Setenv("FAKE_DF_EXIT", "0")
	if err := b.ExportBatch(yamlPath, 3, filepath.Join(work, "after_stop.csv")); err != nil {
		t.Fatalf("STAGE7-STATE-005: Batch must be retryable after Stop: %v", err)
	}
}

func batchMarker(res bindings.BatchResult) string {
	for _, row := range res.Rows {
		if v, ok := row["marker"]; ok {
			return stringify(v)
		}
	}
	// Fallback: scan any string cell.
	for _, row := range res.Rows {
		for _, v := range row {
			s := stringify(v)
			if strings.Contains(s, "task_") || strings.Contains(s, "CONTENT_") {
				return s
			}
		}
	}
	return ""
}

func stringify(v any) string {
	switch x := v.(type) {
	case string:
		return x
	default:
		return ""
	}
}

func readCSVMarkers(t *testing.T, path string) []string {
	t.Helper()
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	r := csv.NewReader(f)
	records, err := r.ReadAll()
	if err != nil {
		t.Fatal(err)
	}
	if len(records) < 2 {
		return nil
	}
	header := records[0]
	idx := -1
	for i, h := range header {
		if h == "marker" {
			idx = i
			break
		}
	}
	if idx < 0 {
		t.Fatalf("marker column missing in %s", path)
	}
	out := make([]string, 0, len(records)-1)
	for _, row := range records[1:] {
		if idx < len(row) {
			out = append(out, row[idx])
		}
	}
	return out
}
