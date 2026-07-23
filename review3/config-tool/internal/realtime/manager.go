package realtime

import (
	"context"
	"fmt"
	"path/filepath"
	"sync"

	"github.com/google/uuid"
)

type Manager struct {
	storage  *ProjectStorage
	compiler RealtimeCompiler
	mu       sync.Mutex
}

func NewManager(storage *ProjectStorage, compiler RealtimeCompiler) *Manager {
	return &Manager{storage: storage, compiler: compiler}
}

func (m *Manager) ListProjects(_ context.Context) ([]ProjectSummary, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.storage.ListProjects()
}

func (m *Manager) CreateProject(_ context.Context, name string) (Project, error) {
	if name == "" {
		return Project{}, fmt.Errorf("工程名称不能为空")
	}
	m.mu.Lock()
	defer m.mu.Unlock()

	id := uuid.New().String()
	p := Project{
		Version: 1,
		ID:      id,
		Name:    name,
		Sources: []Source{},
	}
	if err := m.storage.SaveProject(p); err != nil {
		return Project{}, err
	}
	return p, nil
}

func (m *Manager) OpenProject(_ context.Context, id string) (Project, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.storage.LoadProject(id)
}

func (m *Manager) DeleteProject(_ context.Context, id string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.storage.DeleteProject(id)
}

func (m *Manager) RenameProject(_ context.Context, id, newName string) (Project, error) {
	if newName == "" {
		return Project{}, fmt.Errorf("工程名称不能为空")
	}
	m.mu.Lock()
	defer m.mu.Unlock()

	p, err := m.storage.LoadProject(id)
	if err != nil {
		return Project{}, err
	}
	p.Name = newName
	if err := m.storage.SaveProject(p); err != nil {
		return Project{}, err
	}
	return p, nil
}

func (m *Manager) AddSource(ctx context.Context, projectID, yamlPath string) (ProjectView, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	p, err := m.storage.LoadProject(projectID)
	if err != nil {
		return ProjectView{}, err
	}

	sourceID := uuid.New().String()
	baseName := filepath.Base(yamlPath)

	if err := m.storage.CopySourceFile(projectID, sourceID, yamlPath); err != nil {
		return ProjectView{}, err
	}

	candidate := make([]Source, len(p.Sources), len(p.Sources)+1)
	copy(candidate, p.Sources)
	candidate = append(candidate, Source{
		ID:       sourceID,
		Name:     baseName,
		File:     "sources/" + sourceID + ".yaml",
		Replicas: 1,
	})

	result, err := m.validateCandidate(ctx, projectID, candidate)
	if err != nil {
		m.storage.RemoveSourceFile(projectID, sourceID)
		return ProjectView{}, err
	}
	if !result.Valid {
		m.storage.RemoveSourceFile(projectID, sourceID)
		return ProjectView{Applied: false, Project: p, Validation: result}, nil
	}

	p.Sources = candidate
	if err := m.storage.SaveProject(p); err != nil {
		m.storage.RemoveSourceFile(projectID, sourceID)
		return ProjectView{}, err
	}

	return ProjectView{Applied: true, Project: p, Validation: result}, nil
}

func (m *Manager) RemoveSource(ctx context.Context, projectID, sourceID string) (ProjectView, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	p, err := m.storage.LoadProject(projectID)
	if err != nil {
		return ProjectView{}, err
	}

	found := false
	var newSources []Source
	for _, s := range p.Sources {
		if s.ID == sourceID {
			found = true
			continue
		}
		newSources = append(newSources, s)
	}
	if !found {
		return ProjectView{}, fmt.Errorf("来源不存在: %s", sourceID)
	}

	p.Sources = newSources
	if p.Sources == nil {
		p.Sources = []Source{}
	}

	result, err := m.validateCandidate(ctx, projectID, p.Sources)
	if err != nil {
		return ProjectView{}, err
	}

	if err := m.storage.SaveProject(p); err != nil {
		return ProjectView{}, err
	}
	m.storage.RemoveSourceFile(projectID, sourceID)

	return ProjectView{Applied: true, Project: p, Validation: result}, nil
}

func (m *Manager) UpdateReplicas(ctx context.Context, projectID, sourceID string, replicas int) (ProjectView, error) {
	if replicas < MinReplicas || replicas > MaxReplicas {
		return ProjectView{}, fmt.Errorf("副本数必须在 %d~%d 之间", MinReplicas, MaxReplicas)
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	p, err := m.storage.LoadProject(projectID)
	if err != nil {
		return ProjectView{}, err
	}

	found := false
	candidate := make([]Source, len(p.Sources))
	copy(candidate, p.Sources)
	for i := range candidate {
		if candidate[i].ID == sourceID {
			candidate[i].Replicas = replicas
			found = true
			break
		}
	}
	if !found {
		return ProjectView{}, fmt.Errorf("来源不存在: %s", sourceID)
	}

	result, err := m.validateCandidate(ctx, projectID, candidate)
	if err != nil {
		return ProjectView{}, err
	}
	if !result.Valid {
		return ProjectView{Applied: false, Project: p, Validation: result}, nil
	}

	p.Sources = candidate
	if err := m.storage.SaveProject(p); err != nil {
		return ProjectView{}, err
	}

	return ProjectView{Applied: true, Project: p, Validation: result}, nil
}

func (m *Manager) ValidateProject(ctx context.Context, projectID string) (ValidationResult, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	p, err := m.storage.LoadProject(projectID)
	if err != nil {
		return ValidationResult{}, err
	}
	return m.validateCandidate(ctx, projectID, p.Sources)
}

func (m *Manager) CompileProject(ctx context.Context, projectID, outputPath string) (string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	p, err := m.storage.LoadProject(projectID)
	if err != nil {
		return "", err
	}
	if len(p.Sources) == 0 {
		return "", fmt.Errorf("工程没有 YAML 来源")
	}

	specs := make([]CompilerSourceSpec, len(p.Sources))
	for i, s := range p.Sources {
		specs[i] = CompilerSourceSpec{
			ID:       s.ID,
			File:     m.storage.SourceAbsPath(projectID, s.ID),
			Replicas: s.Replicas,
		}
	}
	return m.compiler.Compile(ctx, specs, outputPath)
}

func (m *Manager) validateCandidate(ctx context.Context, projectID string, sources []Source) (ValidationResult, error) {
	if len(sources) == 0 {
		return ValidationResult{Valid: true, Instances: []ExpandedInstance{}, Duplicates: []DuplicateInstance{}}, nil
	}

	specs := make([]CompilerSourceSpec, len(sources))
	for i, s := range sources {
		specs[i] = CompilerSourceSpec{
			ID:       s.ID,
			File:     m.storage.SourceAbsPath(projectID, s.ID),
			Replicas: s.Replicas,
		}
	}
	return m.compiler.Validate(ctx, specs)
}

func (m *Manager) localValidation(_ []Source) ValidationResult {
	return ValidationResult{Valid: true, Instances: []ExpandedInstance{}, Duplicates: []DuplicateInstance{}}
}
