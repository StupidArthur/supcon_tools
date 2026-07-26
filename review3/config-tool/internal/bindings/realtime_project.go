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
	// serviceClient 用于同步工程上下文到常驻服务（todo.md §8）。
	// 由 container 在服务启动后注入。
	serviceClient     *DataFactoryServiceClient
	projectFileSetter func(string)
}

func NewRealtimeProjectBinding(manager *realtime.Manager) *RealtimeProjectBinding {
	return &RealtimeProjectBinding{manager: manager}
}

// SetServiceClient 注入服务客户端（todo.md §8）。
func (b *RealtimeProjectBinding) SetServiceClient(client *DataFactoryServiceClient) {
	b.serviceClient = client
}

// SetProjectFileSetter 注入 compiler 的 projectFile 设置回调。
func (b *RealtimeProjectBinding) SetProjectFileSetter(fn func(string)) {
	b.projectFileSetter = fn
}

func (b *RealtimeProjectBinding) SetContext(ctx context.Context) {
	b.ctx = ctx
}

func (b *RealtimeProjectBinding) ListProjects() ([]realtime.ProjectSummary, error) {
	return b.manager.ListProjects(b.ctx)
}

// CreateProject 在 EXE 同级目录的 project/<name>/ 下创建工程。
// 不再让用户选择父目录（设计文档 §二.3）。
func (b *RealtimeProjectBinding) CreateProject(name string) (realtime.OpenedProject, error) {
	parentDir, err := EnsureProjectsRootDir()
	if err != nil {
		return realtime.OpenedProject{}, err
	}
	proj, err := b.manager.CreateProjectAt(b.ctx, name, parentDir)
	if err != nil {
		return realtime.OpenedProject{}, err
	}
	// todo.md §8.1：新建工程后同步到服务
	if syncErr := b.syncProjectOpen(proj.ProjectFile); syncErr != nil {
		// 同步失败不阻断主流程，但记录错误（todo.md §8.4）
		// 前端可通过后续 reload 重试
	}
	return proj, nil
}

func (b *RealtimeProjectBinding) CreateProjectAt(name, parentDir string) (realtime.OpenedProject, error) {
	proj, err := b.manager.CreateProjectAt(b.ctx, name, parentDir)
	if err != nil {
		return realtime.OpenedProject{}, err
	}
	// todo.md §8.1：新建工程后同步到服务
	if syncErr := b.syncProjectOpen(proj.ProjectFile); syncErr != nil {
		// 同步失败不阻断主流程
	}
	return proj, nil
}

func (b *RealtimeProjectBinding) OpenProjectFile(projectFile string) (realtime.OpenedProject, error) {
	proj, err := b.manager.OpenProjectFile(b.ctx, projectFile)
	if err != nil {
		return realtime.OpenedProject{}, err
	}
	// todo.md §8.1：打开工程后同步到服务
	if syncErr := b.syncProjectOpen(proj.ProjectFile); syncErr != nil {
		// 同步失败不阻断主流程
	}
	return proj, nil
}

func (b *RealtimeProjectBinding) AddSourceAt(projectID, projectFile, yamlPath string) (realtime.OpenedProjectView, error) {
	view, err := b.manager.AddSourceAt(b.ctx, projectID, projectFile, yamlPath)
	if err != nil {
		return realtime.OpenedProjectView{}, err
	}
	// todo.md §8.2：添加 YAML 成功后同步到服务
	if view.Applied {
		if syncErr := b.syncProjectReload(); syncErr != nil {
			// 同步失败不阻断主流程
		}
	}
	return view, nil
}

func (b *RealtimeProjectBinding) RemoveSourceAt(projectID, projectFile, sourceID string) (realtime.OpenedProjectView, error) {
	view, err := b.manager.RemoveSourceAt(b.ctx, projectID, projectFile, sourceID)
	if err != nil {
		return realtime.OpenedProjectView{}, err
	}
	// todo.md §8.2：移除 YAML 成功后同步到服务
	if view.Applied {
		if syncErr := b.syncProjectReload(); syncErr != nil {
			// 同步失败不阻断主流程
		}
	}
	return view, nil
}

func (b *RealtimeProjectBinding) UpdateReplicasAt(projectID, projectFile, sourceID string, replicas int) (realtime.OpenedProjectView, error) {
	view, err := b.manager.UpdateReplicasAt(b.ctx, projectID, projectFile, sourceID, replicas)
	if err != nil {
		return realtime.OpenedProjectView{}, err
	}
	// todo.md §8.2：修改副本数成功后同步到服务
	if view.Applied {
		if syncErr := b.syncProjectReload(); syncErr != nil {
			// 同步失败不阻断主流程
		}
	}
	return view, nil
}

func (b *RealtimeProjectBinding) UpdateRuntime(projectID, projectFile string, rt realtime.Runtime) (realtime.OpenedProject, error) {
	proj, err := b.manager.UpdateRuntimeAt(b.ctx, projectID, projectFile, rt)
	if err != nil {
		return realtime.OpenedProject{}, err
	}
	// todo.md §8.2：修改 runtime 成功后同步到服务
	if syncErr := b.syncProjectReload(); syncErr != nil {
		// 同步失败不阻断主流程
	}
	return proj, nil
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

// CurrentAPIToken todo.md §13.2：前端不持有 Token，由 Go 代理。
// 保留函数签名供旧测试编译，但始终返回空字符串。
func CurrentAPIToken() string {
	return ""
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
	exeDir, err := ResolveExeDir()
	if err != nil {
		return "", err
	}
	dir := filepath.Join(exeDir, "project", "realtime_projects")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	return dir, nil
}

// ChooseProjectFile 打开文件选择器，让用户选择 project.yaml。
// 文件选择器默认进入 <EXE 同级目录>/project/（设计文档 §三 路径统一规则）。
// 打开前再次调用 EnsureAppWorkspaceDirs 兜底，确保目录存在。
func (b *RealtimeProjectBinding) ChooseProjectFile() (string, error) {
	if b.ctx == nil {
		return "", fmt.Errorf("wails context 未注入")
	}
	defaultDir, err := defaultDirForChoose(ResolveProjectsRootDir)
	if err != nil {
		return "", fmt.Errorf("工程目录初始化失败: %w", err)
	}
	path, err := runtime.OpenFileDialog(b.ctx, runtime.OpenDialogOptions{
		Title:            "选择 project.yaml",
		DefaultDirectory: defaultDir,
		Filters: []runtime.FileFilter{
			{DisplayName: "工程文件", Pattern: "project.yaml;*.yaml"},
		},
	})
	if err != nil {
		return "", err
	}
	return path, nil
}

// ChooseSourceYAML 选择待添加的 YAML 文件。
func (b *RealtimeProjectBinding) ChooseSourceYAML() (string, error) {
	if b.ctx == nil {
		return "", fmt.Errorf("wails context 未注入")
	}
	path, err := runtime.OpenFileDialog(b.ctx, runtime.OpenDialogOptions{
		Title: "选择 YAML 文件",
		Filters: []runtime.FileFilter{
			{DisplayName: "YAML 文件", Pattern: "*.yaml;*.yml"},
		},
	})
	if err != nil {
		return "", err
	}
	return path, nil
}

// ChooseYamlForDsl 打开 YAML 文件选择器，默认进入 <EXE 同级目录>/template/。
// 用于组态调试首页"打开 YML"按钮（设计文档 §一.1）。
// 打开前再次调用 EnsureAppWorkspaceDirs 兜底，确保目录存在。
func (b *RealtimeProjectBinding) ChooseYamlForDsl() (string, error) {
	if b.ctx == nil {
		return "", fmt.Errorf("wails context 未注入")
	}
	defaultDir, err := defaultDirForChoose(ResolveTemplateDir)
	if err != nil {
		return "", fmt.Errorf("模板目录初始化失败: %w", err)
	}
	path, err := runtime.OpenFileDialog(b.ctx, runtime.OpenDialogOptions{
		Title:            "打开 YML",
		DefaultDirectory: defaultDir,
		Filters: []runtime.FileFilter{
			{DisplayName: "YAML 文件", Pattern: "*.yaml;*.yml"},
		},
	})
	if err != nil {
		return "", err
	}
	return path, nil
}

// defaultDirForChoose 在显示文件选择器前确保默认目录存在（todo.md §4.3）。
// 返回 (路径, error)；失败时返回错误，不静默打开其他目录。
func defaultDirForChoose(resolve func() (string, error)) (string, error) {
	if _, err := EnsureAppWorkspaceDirs(); err != nil {
		return "", err
	}
	p, err := resolve()
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(p, 0o755); err != nil {
		return "", fmt.Errorf("创建目录失败: %w", err)
	}
	return p, nil
}

// SetQuality 写入 OPC UA 质量码覆盖。
func (b *RealtimeProjectBinding) SetQuality(apiHost string, apiPort int, tag, quality string) error {
	reqBody := map[string]any{"tag": tag, "quality": quality}
	data, err := json.Marshal(reqBody)
	if err != nil {
		return err
	}
	resp, err := httpPostJSON(forceHTTPClient, b.forceURL(apiHost, apiPort, "/api/quality"), data)
	if err != nil {
		return err
	}
	return decodeForceResponse(resp, nil)
}

// ClearQuality 清除 OPC UA 质量码覆盖。
func (b *RealtimeProjectBinding) ClearQuality(apiHost string, apiPort int, tag string) error {
	req, _ := http.NewRequest("DELETE", b.forceURL(apiHost, apiPort, "/api/quality/"+tag), nil)
	resp, err := forceHTTPClient.Do(req)
	if err != nil {
		return err
	}
	return decodeForceResponse(resp, nil)
}

// GetQualities 查询当前所有质量码覆盖状态。
func (b *RealtimeProjectBinding) GetQualities(apiHost string, apiPort int) (map[string]any, error) {
	return httpGetJSON(forceHTTPClient, b.forceURL(apiHost, apiPort, "/api/quality"))
}

// SetRuntimeValue 包装现有 /api/instances/{name}/override，把 value 写入 Engine 运行变量。
func (b *RealtimeProjectBinding) SetRuntimeValue(apiHost string, apiPort int, instanceName, tag string, value float64) error {
	reqBody := map[string]any{"tag": tag, "value": value}
	data, err := json.Marshal(reqBody)
	if err != nil {
		return err
	}
	resp, err := httpPostJSON(forceHTTPClient, b.forceURL(apiHost, apiPort, "/api/instances/"+instanceName+"/override"), data)
	if err != nil {
		return err
	}
	return decodeForceResponse(resp, nil)
}

// ---------------------------------------------------------------------------
// todo.md §8：工程上下文同步到常驻服务
// ---------------------------------------------------------------------------

// syncProjectOpen 通知服务打开工程（todo.md §8.1）。
// 在 CreateProject / OpenProjectFile / OpenRecentProject 成功后调用。
func (b *RealtimeProjectBinding) syncProjectOpen(projectFile string) error {
	// 设置 compiler 的 projectFile（用于 /api/project/inspect 和 /api/project/compile）
	if b.projectFileSetter != nil {
		b.projectFileSetter(projectFile)
	}
	if b.serviceClient == nil {
		return nil
	}
	req := map[string]string{"projectFile": projectFile}
	var resp struct {
		OK bool `json:"ok"`
	}
	if err := b.serviceClient.DoJSON(b.ctx, "POST", "/api/project/open", req, &resp); err != nil {
		fmt.Fprintf(os.Stderr, "[realtime] syncProjectOpen 失败: %v\n", err)
		return err
	}
	return nil
}

// syncProjectReload 通知服务重新加载工程（todo.md §8.2）。
// 在 AddSource / RemoveSource / UpdateReplicas / UpdateRuntime 成功后调用。
func (b *RealtimeProjectBinding) syncProjectReload() error {
	if b.serviceClient == nil {
		return nil
	}
	var resp struct {
		OK bool `json:"ok"`
	}
	return b.serviceClient.DoJSON(b.ctx, "POST", "/api/project/reload", nil, &resp)
}

// syncProjectClose 通知服务关闭工程（todo.md §8.3）。
func (b *RealtimeProjectBinding) syncProjectClose() error {
	if b.serviceClient == nil {
		return nil
	}
	var resp struct {
		OK bool `json:"ok"`
	}
	return b.serviceClient.DoJSON(b.ctx, "POST", "/api/project/close", nil, &resp)
}
