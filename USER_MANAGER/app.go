package main

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"sync"

	"github.com/google/uuid"
	wruntime "github.com/wailsapp/wails/v2/pkg/runtime"

	"user-manager/internal/api"
	"user-manager/internal/batch"
	"user-manager/internal/config"
	excelparse "user-manager/internal/excel"
)

// App 是 Wails 绑定层。
// 所有暴露给前端的方法都在这里；核心逻辑委托给 internal/* 包。
type App struct {
	ctx context.Context

	mu      sync.Mutex
	client  *api.Client        // 当前会话的 API 客户端（login 后才有）
	tenID   string             // 当前会话的 tenantID（与 client 配对）
	batches map[string]*batchState // 活跃的批量任务（按 batchID 索引）
}

// batchState 是单次批量任务的内部状态。
type batchState struct {
	Total    int                  `json:"total"`
	Done     int                  `json:"done"`
	Failed   int                  `json:"failed"`
	Results  []batch.CreateResult `json:"results"`
	Cancel   context.CancelFunc   `json:"-"`
}

// NewApp 构造空 App。
func NewApp() *App {
	return &App{
		batches: map[string]*batchState{},
	}
}

// startup 在 Wails 启动时调用，保存 ctx。
func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
	slog.Info("app starting", "version", "v0.1.0")
}

// shutdown 在 Wails 关闭前调用。
func (a *App) shutdown(ctx context.Context) {
	slog.Info("app shutting down")
}

// ============ 登录态 ============

// LoadLoginConfig 启动时读 config.json，回填 URL/TenantID。
func (a *App) LoadLoginConfig() *api.LoginConfig {
	c, err := config.Load()
	if err != nil {
		slog.Error("load config", "err", err)
		return &api.LoginConfig{}
	}
	return &api.LoginConfig{URL: c.URL, TenantID: c.TenantID}
}

// SaveLoginConfig 写 URL/TenantID 到 config.json（不存密码）。
func (a *App) SaveLoginConfig(url, tenantID string) bool {
	if err := config.Save(&config.Config{URL: url, TenantID: tenantID}); err != nil {
		slog.Error("save config", "err", err)
		return false
	}
	return true
}

// Login 登录 TPT 后台。成功返回 null。
func (a *App) Login(url, username, password, tenantID string) *api.OperationStatus {
	a.mu.Lock()
	defer a.mu.Unlock()

	a.client = api.NewClient(url)
	a.tenID = tenantID
	if err := a.client.Login(a.ctx, username, password, tenantID); err != nil {
		slog.Error("login", "user", username, "err", err)
		return errorToOpStatus(err)
	}
	slog.Info("login ok", "user", username, "tenant", tenantID)
	return &api.OperationStatus{Code: "00000", Msg: "ok"}
}

// Logout 清登录态（不清 config.json，下次启动仍回填 URL/TenantID）。
func (a *App) Logout() bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.client != nil {
		a.client.Logout()
	}
	a.client = nil
	return true
}

// IsLoggedIn 报告是否已登录。
func (a *App) IsLoggedIn() bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.client != nil && a.client.IsLoggedIn()
}

// ============ 用户列表 ============

// ListUsers 单页列表。
func (a *App) ListUsers(page, pageSize int, keyword string) *api.PageResponse {
	a.mu.Lock()
	c := a.client
	a.mu.Unlock()
	if c == nil {
		return &api.PageResponse{}
	}
	resp, err := c.ListUsers(a.ctx, page, pageSize, "", keyword, "")
	if err != nil {
		slog.Error("list users", "err", err)
		// 不抛 panic，返回空结构；前端根据 Records 长度判定
		return &api.PageResponse{}
	}
	return resp
}

// GetAllUsers 自动翻页拉全部。
func (a *App) GetAllUsers(keyword string) []api.User {
	a.mu.Lock()
	c := a.client
	a.mu.Unlock()
	if c == nil {
		return nil
	}
	users, err := c.GetAllUsers(a.ctx, keyword, "", 200)
	if err != nil {
		slog.Error("get all users", "err", err)
		return nil
	}
	return users
}

// ============ 单条操作 ============

// CreateUser 创建单个用户。
func (a *App) CreateUser(input api.UserDraft) *api.OperationStatus {
	a.mu.Lock()
	c := a.client
	a.mu.Unlock()
	if c == nil {
		return &api.OperationStatus{Code: "E_LOGIN", Msg: "未登录"}
	}
	st, err := c.CreateUser(a.ctx, input)
	if err != nil {
		return errorToOpStatus(err)
	}
	slog.Info("create user", "username", input.Username, "code", st.Code)
	return st
}

// ResetPassword 重置密码。
func (a *App) ResetPassword(userID int64, newPassword string) *api.OperationStatus {
	a.mu.Lock()
	c := a.client
	a.mu.Unlock()
	if c == nil {
		return &api.OperationStatus{Code: "E_LOGIN", Msg: "未登录"}
	}
	st, err := c.ResetPassword(a.ctx, userID, newPassword)
	if err != nil {
		return errorToOpStatus(err)
	}
	slog.Info("reset password", "userID", userID, "code", st.Code)
	return st
}

// ============ 批量创建 ============

// DownloadBatchTemplate 弹保存框让用户选位置，写入批量创建 xlsx 模板（含 1 行示例）。
// 返回保存的路径；空字符串 = 用户取消或失败。
func (a *App) DownloadBatchTemplate() string {
	path, err := wruntime.SaveFileDialog(a.ctx, wruntime.SaveDialogOptions{
		Title:           "保存批量创建模板",
		DefaultFilename: "batch_users_template.xlsx",
		Filters: []wruntime.FileFilter{
			{DisplayName: "Excel", Pattern: "*.xlsx"},
		},
	})
	if err != nil || path == "" {
		return ""
	}
	f, err := createFile(path)
	if err != nil {
		slog.Error("create template file", "path", path, "err", err)
		return ""
	}
	defer f.Close()
	if err := excelparse.WriteTemplate(f); err != nil {
		slog.Error("write template", "path", path, "err", err)
		return ""
	}
	slog.Info("template saved", "path", path)
	return path
}

// ParseExcelFile 解析 .xlsx → 前端预览用。
func (a *App) ParseExcelFile(path string) *excelparse.ParseResult {
	res, err := excelparse.ParseFile(path, "")
	if err != nil {
		slog.Error("parse xlsx", "path", path, "err", err)
		return &excelparse.ParseResult{
			Filename: path,
			Errors:   []excelparse.ParseErr{{Row: 0, Msg: err.Error()}},
		}
	}
	return res
}

// PickExcelFile 弹出文件选择框。
func (a *App) PickExcelFile() string {
	path, err := wruntime.OpenFileDialog(a.ctx, wruntime.OpenDialogOptions{
		Title: "选择 xlsx 文件",
		Filters: []wruntime.FileFilter{
			{DisplayName: "Excel", Pattern: "*.xlsx"},
		},
	})
	if err != nil {
		slog.Error("open file dialog", "err", err)
		return ""
	}
	return path
}

// BatchCreateUsers 异步批量创建；返回 batchID 用于订阅进度事件。
func (a *App) BatchCreateUsers(drafts []api.UserDraft, concurrency int) string {
	a.mu.Lock()
	c := a.client
	a.mu.Unlock()
	if c == nil {
		return ""
	}

	batchID := uuid.NewString()[:12]
	bctx, cancel := context.WithCancel(a.ctx)

	st := &batchState{
		Total:   len(drafts),
		Results: make([]batch.CreateResult, len(drafts)),
		Cancel:  cancel,
	}
	a.mu.Lock()
	a.batches[batchID] = st
	a.mu.Unlock()

	emitEvent := func(p batch.BatchProgress) {
		wruntime.EventsEmit(a.ctx, "batch:progress", map[string]any{
			"batchId":  batchID,
			"progress": p,
		})
	}

	go func() {
		slog.Info("batch start", "batchID", batchID, "total", len(drafts), "concurrency", concurrency)
		emitEvent(batch.BatchProgress{Total: len(drafts), Last: &batch.CreateResult{}})

		results, _ := batch.BatchCreateUsers(bctx, c, drafts, concurrency, emitEvent)

		a.mu.Lock()
		st.Results = results
		st.Done = len(results)
		for _, r := range results {
			if !r.Success {
				st.Failed++
			}
		}
		finished := batch.BatchProgress{
			Done:     st.Done,
			Failed:   st.Failed,
			Total:    st.Total,
			Last:     nil,
			Finished: true,
		}
		a.mu.Unlock()

		wruntime.EventsEmit(a.ctx, "batch:done", map[string]any{
			"batchId": batchID,
			"summary": finished,
			"results": results,
		})
		slog.Info("batch done", "batchID", batchID, "failed", st.Failed)
	}()

	return batchID
}

// CancelBatch 取消进行中的批量任务。
func (a *App) CancelBatch(batchID string) bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	st, ok := a.batches[batchID]
	if !ok {
		return false
	}
	st.Cancel()
	delete(a.batches, batchID)
	return true
}

// ============ 辅助 ============

// errorToOpStatus 把 error 转成 OperationStatus（避免 panic，前端统一看 code/msg）。
func errorToOpStatus(err error) *api.OperationStatus {
	if err == nil {
		return &api.OperationStatus{Code: "00000", Msg: "ok"}
	}
	st := &api.OperationStatus{Code: "E_UNKNOWN", Msg: err.Error()}
	var apiErr *api.ErrAPI
	if errors.As(err, &apiErr) {
		st.Code = apiErr.Code
		st.Msg = apiErr.Msg
	}
	var authErr *api.ErrAuthError
	if errors.As(err, &authErr) {
		st.Code = authErr.Code
		st.Msg = authErr.Msg
	}
	return st
}

// createFile 抽出来便于未来扩展（如抽权限位、原子写）。
func createFile(path string) (*os.File, error) {
	return os.Create(path)
}
