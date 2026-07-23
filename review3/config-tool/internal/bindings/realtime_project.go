package bindings

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sync"
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

func (b *RealtimeProjectBinding) ListAlarmRules(projectID string) ([]realtime.AlarmRule, error) {
	return b.manager.ListAlarmRules(b.ctx, projectID)
}

func (b *RealtimeProjectBinding) CreateAlarmRule(projectID string, rule realtime.AlarmRule) ([]realtime.AlarmRule, error) {
	return b.manager.CreateAlarmRule(b.ctx, projectID, rule)
}

func (b *RealtimeProjectBinding) UpdateAlarmRule(projectID string, rule realtime.AlarmRule) ([]realtime.AlarmRule, error) {
	return b.manager.UpdateAlarmRule(b.ctx, projectID, rule)
}

func (b *RealtimeProjectBinding) DeleteAlarmRule(projectID string, alarmID string) ([]realtime.AlarmRule, error) {
	return b.manager.DeleteAlarmRule(b.ctx, projectID, alarmID)
}

func (b *RealtimeProjectBinding) ValidateAlarmRules(projectID string) error {
	return b.manager.ValidateAlarmRules(b.ctx, projectID)
}

func (b *RealtimeProjectBinding) GetDashboard(projectID string) (realtime.Dashboard, error) {
	return b.manager.GetDashboard(b.ctx, projectID)
}

func (b *RealtimeProjectBinding) SaveDashboard(projectID string, d realtime.Dashboard) (realtime.Dashboard, error) {
	return b.manager.SaveDashboard(b.ctx, projectID, d)
}

func (b *RealtimeProjectBinding) CompileProject(projectID, outputPath string) (string, error) {
	return b.manager.CompileProject(b.ctx, projectID, outputPath)
}

type ForceSetRequest struct {
	Tag      string   `json:"tag"`
	Mode     string   `json:"mode"`
	Value    *float64 `json:"value,omitempty"`
	Duration *float64 `json:"duration,omitempty"`
}

type ForceEntry struct {
	Mode      string   `json:"mode"`
	Value     *float64 `json:"value,omitempty"`
	ExpiresAt *float64 `json:"expires_at,omitempty"`
}

var forceHTTPClient = &http.Client{Timeout: 5 * time.Second}

var (
	tokenMu       sync.Mutex
	currentToken  string
)

func SetCurrentAPIToken(token string) {
	tokenMu.Lock()
	defer tokenMu.Unlock()
	currentToken = token
}

func CurrentAPIToken() string {
	tokenMu.Lock()
	defer tokenMu.Unlock()
	return currentToken
}

func applyAuth(req *http.Request) {
	if t := CurrentAPIToken(); t != "" {
		req.Header.Set("Authorization", "Bearer "+t)
	}
}

func httpPostJSON(client *http.Client, url string, body []byte) (*http.Response, error) {
	req, err := http.NewRequest("POST", url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	applyAuth(req)
	return client.Do(req)
}

func (b *RealtimeProjectBinding) forceURL(apiHost string, apiPort int, path string) string {
	return fmt.Sprintf("http://%s:%d%s", apiHost, apiPort, path)
}

func decodeForceResponse(resp *http.Response, out any) error {
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		var errBody struct {
			Detail string `json:"detail"`
		}
		if json.Unmarshal(body, &errBody) == nil && errBody.Detail != "" {
			return fmt.Errorf("%s", errBody.Detail)
		}
		return fmt.Errorf("强制操作失败: HTTP %d", resp.StatusCode)
	}
	if out != nil {
		if err := json.Unmarshal(body, out); err != nil {
			return fmt.Errorf("解析强制响应失败: %w", err)
		}
	}
	return nil
}

func httpGetJSON(client *http.Client, url string) (map[string]any, error) {
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, err
	}
	applyAuth(req)
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("请求失败: HTTP %d", resp.StatusCode)
	}
	var out map[string]any
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("解析响应失败: %w", err)
	}
	return out, nil
}

func (b *RealtimeProjectBinding) SetForce(apiHost string, apiPort int, tag, mode string, value *float64, duration *float64) error {
	reqBody := ForceSetRequest{Tag: tag, Mode: mode, Value: value, Duration: duration}
	data, err := json.Marshal(reqBody)
	if err != nil {
		return fmt.Errorf("序列化请求失败: %w", err)
	}
	resp, err := httpPostJSON(forceHTTPClient, b.forceURL(apiHost, apiPort, "/api/force"), data)
	if err != nil {
		return err
	}
	var out struct {
		OK bool `json:"ok"`
	}
	if err := decodeForceResponse(resp, &out); err != nil {
		return err
	}
	if !out.OK {
		return fmt.Errorf("设置强制失败")
	}
	return nil
}

func (b *RealtimeProjectBinding) ClearForce(apiHost string, apiPort int, tag string) error {
	req, _ := http.NewRequest("DELETE", b.forceURL(apiHost, apiPort, "/api/force/"+tag), nil)
	resp, err := forceHTTPClient.Do(req)
	if err != nil {
		return err
	}
	return decodeForceResponse(resp, nil)
}

func (b *RealtimeProjectBinding) ClearAllForces(apiHost string, apiPort int) error {
	req, _ := http.NewRequest("DELETE", b.forceURL(apiHost, apiPort, "/api/force"), nil)
	resp, err := forceHTTPClient.Do(req)
	if err != nil {
		return err
	}
	return decodeForceResponse(resp, nil)
}

type ForceState struct {
	Forces map[string]ForceEntry `json:"forces"`
	Tags   []string              `json:"tags"`
}

func (b *RealtimeProjectBinding) GetForces(apiHost string, apiPort int) (ForceState, error) {
	resp, err := forceHTTPClient.Get(b.forceURL(apiHost, apiPort, "/api/force"))
	if err != nil {
		return ForceState{}, err
	}
	var result struct {
		OK     bool                  `json:"ok"`
		Forces map[string]ForceEntry `json:"forces"`
		Tags   []string              `json:"tags"`
	}
	if err := decodeForceResponse(resp, &result); err != nil {
		return ForceState{}, err
	}
	if !result.OK {
		return ForceState{}, fmt.Errorf("获取强制状态失败")
	}
	if result.Forces == nil {
		result.Forces = map[string]ForceEntry{}
	}
	if result.Tags == nil {
		result.Tags = []string{}
	}
	return ForceState{Forces: result.Forces, Tags: result.Tags}, nil
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
