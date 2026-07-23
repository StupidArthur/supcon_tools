package bindings

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"time"

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

func (b *RealtimeProjectBinding) CompileProject(projectID, outputPath string) (string, error) {
	return b.manager.CompileProject(b.ctx, projectID, outputPath)
}

type ForceSetRequest struct {
	Tag   string   `json:"tag"`
	Mode  string   `json:"mode"`
	Value *float64 `json:"value,omitempty"`
}

type ForceEntry struct {
	Mode  string  `json:"mode"`
	Value float64 `json:"value,omitempty"`
}

var forceHTTPClient = &http.Client{Timeout: 5 * time.Second}

func (b *RealtimeProjectBinding) forceURL(apiHost string, apiPort int, path string) string {
	return fmt.Sprintf("http://%s:%d%s", apiHost, apiPort, path)
}

func (b *RealtimeProjectBinding) SetForce(apiHost string, apiPort int, tag, mode string, value *float64) error {
	reqBody := ForceSetRequest{Tag: tag, Mode: mode, Value: value}
	data, _ := json.Marshal(reqBody)
	resp, err := forceHTTPClient.Post(b.forceURL(apiHost, apiPort, "/api/force"), "application/json", bytes.NewReader(data))
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("设置强制失败: HTTP %d", resp.StatusCode)
	}
	return nil
}

func (b *RealtimeProjectBinding) ClearForce(apiHost string, apiPort int, tag string) error {
	req, _ := http.NewRequest("DELETE", b.forceURL(apiHost, apiPort, "/api/force/"+tag), nil)
	resp, err := forceHTTPClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	return nil
}

func (b *RealtimeProjectBinding) ClearAllForces(apiHost string, apiPort int) error {
	req, _ := http.NewRequest("DELETE", b.forceURL(apiHost, apiPort, "/api/force"), nil)
	resp, err := forceHTTPClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	return nil
}

func (b *RealtimeProjectBinding) GetForces(apiHost string, apiPort int) (map[string]ForceEntry, error) {
	resp, err := forceHTTPClient.Get(b.forceURL(apiHost, apiPort, "/api/force"))
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var result struct {
		OK     bool                  `json:"ok"`
		Forces map[string]ForceEntry `json:"forces"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, err
	}
	return result.Forces, nil
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
