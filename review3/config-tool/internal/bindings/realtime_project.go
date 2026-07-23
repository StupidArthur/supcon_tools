package bindings

import (
	"context"
	"os"
	"path/filepath"

	"config-tool/internal/realtime"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

type RealtimeProjectBinding struct {
	ctx     context.Context
	manager *realtime.Manager
}

func NewRealtimeProjectBinding(manager *realtime.Manager) *RealtimeProjectBinding {
	return &RealtimeProjectBinding{manager: manager}
}

func (b *RealtimeProjectBinding) SetContext(ctx context.Context) {
	b.ctx = ctx
}

func (b *RealtimeProjectBinding) ListProjects() ([]realtime.ProjectSummary, error) {
	return b.manager.ListProjects(b.ctx)
}

func (b *RealtimeProjectBinding) CreateProject(name string) (realtime.Project, error) {
	return b.manager.CreateProject(b.ctx, name)
}

func (b *RealtimeProjectBinding) OpenProject(id string) (realtime.Project, error) {
	return b.manager.OpenProject(b.ctx, id)
}

func (b *RealtimeProjectBinding) DeleteProject(id string) error {
	return b.manager.DeleteProject(b.ctx, id)
}

func (b *RealtimeProjectBinding) RenameProject(id, newName string) (realtime.Project, error) {
	return b.manager.RenameProject(b.ctx, id, newName)
}

func (b *RealtimeProjectBinding) AddSource(projectID string) (realtime.ProjectView, error) {
	path, err := runtime.OpenFileDialog(b.ctx, runtime.OpenDialogOptions{
		Title: "选择 YAML 文件",
		Filters: []runtime.FileFilter{
			{DisplayName: "YAML 文件", Pattern: "*.yaml;*.yml"},
		},
	})
	if err != nil {
		return realtime.ProjectView{}, err
	}
	if path == "" {
		return realtime.ProjectView{}, nil
	}
	return b.manager.AddSource(b.ctx, projectID, path)
}

func (b *RealtimeProjectBinding) RemoveSource(projectID, sourceID string) (realtime.ProjectView, error) {
	return b.manager.RemoveSource(b.ctx, projectID, sourceID)
}

func (b *RealtimeProjectBinding) UpdateReplicas(projectID, sourceID string, replicas int) (realtime.ProjectView, error) {
	return b.manager.UpdateReplicas(b.ctx, projectID, sourceID, replicas)
}

func (b *RealtimeProjectBinding) ValidateProject(projectID string) (realtime.ValidationResult, error) {
	return b.manager.ValidateProject(b.ctx, projectID)
}

func ResolveRealtimeProjectsDir() (string, error) {
	configDir, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	dir := filepath.Join(configDir, "DataFactory", "realtime_projects")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	return dir, nil
}
