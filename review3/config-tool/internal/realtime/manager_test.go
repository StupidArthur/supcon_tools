package realtime

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

type fakeCompiler struct {
	result ValidationResult
	err    error
	calls  int
}

func (f *fakeCompiler) Validate(_ context.Context, _ []CompilerSourceSpec) (ValidationResult, error) {
	f.calls++
	return f.result, f.err
}

func (f *fakeCompiler) Compile(_ context.Context, _ []CompilerSourceSpec, outputPath string) (string, error) {
	return outputPath, nil
}

func newTestManager(t *testing.T, compiler RealtimeCompiler) *Manager {
	t.Helper()
	dir := t.TempDir()
	storage := NewProjectStorage(dir)
	return NewManager(storage, compiler)
}

func writeYAML(t *testing.T, dir, name, content string) string {
	t.Helper()
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	return p
}

const tankYAML = `clock:
  mode: GENERATOR
  cycle_time: 0.5
program:
  - name: source_flow
    type: Variable
    value: 0.001
  - name: tank
    type: CYLINDRICAL_TANK
    params:
      height: 1.2
    inputs:
      inlet_flow: source_flow
  - name: pid
    type: PID
    params:
      PB: 50.0
    inputs:
      PV: tank.level
`

func validResult() ValidationResult {
	return ValidationResult{
		Valid:      true,
		Instances:  []ExpandedInstance{{Name: "pid", SourceID: "s1", ReplicaIndex: 0, OriginalName: "pid"}},
		Duplicates: []DuplicateInstance{},
	}
}

func duplicateResult() ValidationResult {
	return ValidationResult{
		Valid:     false,
		Instances: []ExpandedInstance{},
		Duplicates: []DuplicateInstance{
			{Name: "pid", Occurrences: []InstanceOrigin{
				{SourceID: "s1", ReplicaIndex: 0, OriginalName: "pid"},
				{SourceID: "s2", ReplicaIndex: 0, OriginalName: "pid"},
			}},
		},
	}
}

func TestCreateProject(t *testing.T) {
	m := newTestManager(t, &fakeCompiler{result: validResult()})
	ctx := context.Background()

	p, err := m.CreateProject(ctx, "测试工程")
	if err != nil {
		t.Fatal(err)
	}
	if p.Name != "测试工程" {
		t.Fatalf("expected name 测试工程, got %s", p.Name)
	}
	if p.ID == "" {
		t.Fatal("expected non-empty ID")
	}
	if p.Version != 1 {
		t.Fatalf("expected version 1, got %d", p.Version)
	}
}

func TestCreateProjectEmptyName(t *testing.T) {
	m := newTestManager(t, &fakeCompiler{result: validResult()})
	_, err := m.CreateProject(context.Background(), "")
	if err == nil {
		t.Fatal("expected error for empty name")
	}
}

func TestProjectIDPathTraversal(t *testing.T) {
	m := newTestManager(t, &fakeCompiler{result: validResult()})
	_, err := m.OpenProject(context.Background(), "../etc")
	if err == nil {
		t.Fatal("expected error for path traversal")
	}
	_, err = m.OpenProject(context.Background(), "..")
	if err == nil {
		t.Fatal("expected error for ..")
	}
}

func TestAddSourceSuccess(t *testing.T) {
	fc := &fakeCompiler{result: validResult()}
	m := newTestManager(t, fc)
	ctx := context.Background()

	p, _ := m.CreateProject(ctx, "proj")
	yamlPath := writeYAML(t, t.TempDir(), "tank.yaml", tankYAML)

	view, err := m.AddSource(ctx, p.ID, yamlPath)
	if err != nil {
		t.Fatal(err)
	}
	if len(view.Project.Sources) != 1 {
		t.Fatalf("expected 1 source, got %d", len(view.Project.Sources))
	}
	if view.Project.Sources[0].Name != "tank.yaml" {
		t.Fatalf("expected tank.yaml, got %s", view.Project.Sources[0].Name)
	}
	if view.Project.Sources[0].Replicas != 1 {
		t.Fatalf("expected replicas 1, got %d", view.Project.Sources[0].Replicas)
	}
	if fc.calls != 1 {
		t.Fatalf("expected 1 compiler call, got %d", fc.calls)
	}
}

func TestAddSourceDuplicateNoResidue(t *testing.T) {
	fc := &fakeCompiler{result: duplicateResult()}
	m := newTestManager(t, fc)
	ctx := context.Background()

	p, _ := m.CreateProject(ctx, "proj")
	yamlPath := writeYAML(t, t.TempDir(), "tank.yaml", tankYAML)

	_, err := m.AddSource(ctx, p.ID, yamlPath)
	if err == nil {
		t.Fatal("expected duplicate error")
	}
	ve, ok := err.(*ValidationError)
	if !ok {
		t.Fatalf("expected ValidationError, got %T", err)
	}
	if ve.Code != "DUPLICATE_INSTANCE_NAMES" {
		t.Fatalf("expected DUPLICATE_INSTANCE_NAMES, got %s", ve.Code)
	}

	reloaded, _ := m.OpenProject(ctx, p.ID)
	if len(reloaded.Sources) != 0 {
		t.Fatalf("expected 0 sources after failed add, got %d", len(reloaded.Sources))
	}
}

func TestAddSourceSameNameNoOverwrite(t *testing.T) {
	fc := &fakeCompiler{result: validResult()}
	m := newTestManager(t, fc)
	ctx := context.Background()

	p, _ := m.CreateProject(ctx, "proj")
	yamlPath := writeYAML(t, t.TempDir(), "tank.yaml", tankYAML)

	view1, _ := m.AddSource(ctx, p.ID, yamlPath)
	view2, _ := m.AddSource(ctx, p.ID, yamlPath)

	if view1.Project.Sources[0].ID == view2.Project.Sources[1].ID {
		t.Fatal("same-name imports should get different source IDs")
	}
}

func TestUpdateReplicasSuccess(t *testing.T) {
	fc := &fakeCompiler{result: validResult()}
	m := newTestManager(t, fc)
	ctx := context.Background()

	p, _ := m.CreateProject(ctx, "proj")
	yamlPath := writeYAML(t, t.TempDir(), "tank.yaml", tankYAML)
	view, _ := m.AddSource(ctx, p.ID, yamlPath)
	sourceID := view.Project.Sources[0].ID

	updated, err := m.UpdateReplicas(ctx, p.ID, sourceID, 5)
	if err != nil {
		t.Fatal(err)
	}
	if updated.Project.Sources[0].Replicas != 5 {
		t.Fatalf("expected replicas 5, got %d", updated.Project.Sources[0].Replicas)
	}
}

func TestUpdateReplicasDuplicateKeepsOld(t *testing.T) {
	fc := &fakeCompiler{result: validResult()}
	m := newTestManager(t, fc)
	ctx := context.Background()

	p, _ := m.CreateProject(ctx, "proj")
	yamlPath := writeYAML(t, t.TempDir(), "tank.yaml", tankYAML)
	view, _ := m.AddSource(ctx, p.ID, yamlPath)
	sourceID := view.Project.Sources[0].ID

	fc.result = duplicateResult()
	_, err := m.UpdateReplicas(ctx, p.ID, sourceID, 10)
	if err == nil {
		t.Fatal("expected duplicate error")
	}

	reloaded, _ := m.OpenProject(ctx, p.ID)
	if reloaded.Sources[0].Replicas != 1 {
		t.Fatalf("expected replicas still 1, got %d", reloaded.Sources[0].Replicas)
	}
}

func TestUpdateReplicasInvalidRange(t *testing.T) {
	fc := &fakeCompiler{result: validResult()}
	m := newTestManager(t, fc)
	ctx := context.Background()

	p, _ := m.CreateProject(ctx, "proj")
	yamlPath := writeYAML(t, t.TempDir(), "tank.yaml", tankYAML)
	view, _ := m.AddSource(ctx, p.ID, yamlPath)
	sourceID := view.Project.Sources[0].ID

	_, err := m.UpdateReplicas(ctx, p.ID, sourceID, 0)
	if err == nil {
		t.Fatal("expected error for replicas=0")
	}
	_, err = m.UpdateReplicas(ctx, p.ID, sourceID, 101)
	if err == nil {
		t.Fatal("expected error for replicas=101")
	}
}

func TestRemoveSource(t *testing.T) {
	fc := &fakeCompiler{result: validResult()}
	m := newTestManager(t, fc)
	ctx := context.Background()

	p, _ := m.CreateProject(ctx, "proj")
	yamlPath := writeYAML(t, t.TempDir(), "tank.yaml", tankYAML)
	view, _ := m.AddSource(ctx, p.ID, yamlPath)
	sourceID := view.Project.Sources[0].ID

	updated, err := m.RemoveSource(ctx, p.ID, sourceID)
	if err != nil {
		t.Fatal(err)
	}
	if len(updated.Project.Sources) != 0 {
		t.Fatalf("expected 0 sources, got %d", len(updated.Project.Sources))
	}
}

func TestDeleteProject(t *testing.T) {
	m := newTestManager(t, &fakeCompiler{result: validResult()})
	ctx := context.Background()

	p, _ := m.CreateProject(ctx, "proj")
	if err := m.DeleteProject(ctx, p.ID); err != nil {
		t.Fatal(err)
	}
	_, err := m.OpenProject(ctx, p.ID)
	if err == nil {
		t.Fatal("expected error opening deleted project")
	}
}

func TestListProjects(t *testing.T) {
	m := newTestManager(t, &fakeCompiler{result: validResult()})
	ctx := context.Background()

	list, _ := m.ListProjects(ctx)
	if len(list) != 0 {
		t.Fatalf("expected 0 projects, got %d", len(list))
	}

	m.CreateProject(ctx, "A")
	m.CreateProject(ctx, "B")
	list, _ = m.ListProjects(ctx)
	if len(list) != 2 {
		t.Fatalf("expected 2 projects, got %d", len(list))
	}
}

func TestOpenCorruptedProjectYAML(t *testing.T) {
	dir := t.TempDir()
	projDir := filepath.Join(dir, "bad-id")
	os.MkdirAll(projDir, 0o755)
	os.WriteFile(filepath.Join(projDir, "project.yaml"), []byte(":::invalid"), 0o644)

	storage := NewProjectStorage(dir)
	_, err := storage.LoadProject("bad-id")
	if err == nil {
		t.Fatal("expected error for corrupted yaml")
	}
}

func TestAtomicWrite(t *testing.T) {
	dir := t.TempDir()
	storage := NewProjectStorage(dir)

	p := Project{Version: 1, ID: "test-atomic", Name: "atomic", Sources: []Source{}}
	if err := storage.SaveProject(p); err != nil {
		t.Fatal(err)
	}

	tmpFile := filepath.Join(dir, "test-atomic", "project.yaml.tmp")
	if _, err := os.Stat(tmpFile); !os.IsNotExist(err) {
		t.Fatal("tmp file should not exist after successful write")
	}

	loaded, err := storage.LoadProject("test-atomic")
	if err != nil {
		t.Fatal(err)
	}
	if loaded.Name != "atomic" {
		t.Fatalf("expected atomic, got %s", loaded.Name)
	}
}
