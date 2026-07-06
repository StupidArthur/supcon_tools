package main

import (
	"context"
	"fmt"
	"time"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

// App 是 Wails 应用主结构，持有全局 AlgAPI 实例和窗口上下文。
type App struct {
	ctx  context.Context
	api  *AlgAPI
}

// NewApp 创建 App 实例。
func NewApp() *App {
	return &App{}
}

// startup 在应用启动时由 Wails 调用，保存 context 供后续使用。
func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
}

// ConnectResult 连接平台的结果。
type ConnectResult struct {
	Success bool   `json:"success"`
	Count   int    `json:"count"`
	Error   string `json:"error"`
}

// Connect 连接平台并登录，全局共享 AlgAPI 实例。
func (a *App) Connect(url, username, password, tenantID string) ConnectResult {
	api := NewAlgAPI(url)
	if err := api.Login(username, password, tenantID); err != nil {
		return ConnectResult{Error: err.Error()}
	}
	if _, err := api.GetAllAlgorithms(); err != nil {
		return ConnectResult{Error: err.Error()}
	}
	a.api = api
	return ConnectResult{Success: true, Count: len(api.algorithms)}
}

// IsConnected 检查是否已连接。
func (a *App) IsConnected() bool {
	return a.api != nil
}

// emitLog 向前端推送日志事件，channel 区分三个功能页的日志。
func (a *App) emitLog(channel, msg string) {
	if a.ctx != nil {
		runtime.EventsEmit(a.ctx, "log:"+channel, msg)
	}
}

// emitEvent 推送自定义事件。
func (a *App) emitEvent(eventName string, data any) {
	if a.ctx != nil {
		runtime.EventsEmit(a.ctx, eventName, data)
	}
}

// SyncStartResult 同步任务启动结果。
type SyncStartResult struct {
	Started bool   `json:"started"`
	Error   string `json:"error"`
}

// StartSync 启动同步任务（异步执行，通过 log:sync 事件推送日志）。
func (a *App) StartSync(dir string, skipEdit bool) SyncStartResult {
	if a.api == nil {
		return SyncStartResult{Error: "请先连接平台"}
	}

	go func() {
		err := a.api.SyncAlgorithms(SyncOptions{Dir: dir, SkipEdit: skipEdit}, func(msg string) {
			a.emitLog("sync", msg)
		})
		if err != nil {
			a.emitLog("sync", fmt.Sprintf("[任务异常] %v", err))
		}
		a.emitEvent("sync:done", nil)
	}()

	return SyncStartResult{Started: true}
}

// ExportAlgorithms 导出算法信息到 CSV 文件。
func (a *App) ExportAlgorithms(savePath string) ConnectResult {
	if a.api == nil {
		return ConnectResult{Error: "请先连接平台"}
	}
	if err := a.api.ExportAlgorithms(savePath); err != nil {
		return ConnectResult{Error: err.Error()}
	}
	return ConnectResult{Success: true, Count: len(a.api.algorithms)}
}

// LoadCSVResult CSV 加载结果。
type LoadCSVResult struct {
	Records []CSVRecord `json:"records"`
	Count   int         `json:"count"`
	Error   string      `json:"error"`
}

// LoadCSVFile 加载 CSV 发布配置文件。
func (a *App) LoadCSVFile(path string) LoadCSVResult {
	records, err := LoadCSV(path)
	if err != nil {
		return LoadCSVResult{Error: err.Error()}
	}
	return LoadCSVResult{Records: records, Count: len(records)}
}

// CompareAlgorithms 比对 CSV 配置与平台算法的差异。
func (a *App) CompareAlgorithms(records []CSVRecord) *CompareResult {
	if a.api == nil {
		return &CompareResult{Error: "请先连接平台"}
	}
	return a.api.CompareAlgorithms(records)
}

// PublishStartResult 发布任务启动结果。
type PublishStartResult struct {
	Started bool   `json:"started"`
	Error   string `json:"error"`
}

// StartPublish 启动批量发布任务（异步执行，通过 log:publish 事件推送日志）。
func (a *App) StartPublish(items []PublishItem, concurrent int) PublishStartResult {
	if a.api == nil {
		return PublishStartResult{Error: "请先连接平台"}
	}

	go func() {
		a.emitLog("publish", fmt.Sprintf("[发布] 开始发布 %d 个算法，并发数: %d", len(items), concurrent))
		a.api.PublishAlgorithms(items, concurrent, func(msg string) {
			a.emitLog("publish", msg)
		})
		a.emitLog("publish", "[发布] 批次发布完成，等待最终校验...")

		stillPending := a.api.VerifyPublished(items, func(msg string) {
			a.emitLog("publish", msg)
		})

		a.emitLog("publish", "============================================================")
		if len(stillPending) > 0 {
			a.emitLog("publish", fmt.Sprintf("[校验完成] %d 个未发布成功:", len(stillPending)))
			for _, name := range stillPending {
				a.emitLog("publish", "  - "+name)
			}
		} else {
			a.emitLog("publish", "[校验完成] 全部发布成功")
		}
		a.emitLog("publish", "============================================================")
		a.emitEvent("publish:done", nil)
	}()

	return PublishStartResult{Started: true}
}

// PublishedAlgosResult 已发布算法列表结果。
type PublishedAlgosResult struct {
	Algos []map[string]any `json:"algos"`
	Count int              `json:"count"`
	Error string           `json:"error"`
}

// GetPublishedAlgorithms 获取平台已发布的算法列表。
func (a *App) GetPublishedAlgorithms() PublishedAlgosResult {
	if a.api == nil {
		return PublishedAlgosResult{Error: "请先连接平台"}
	}

	var released []map[string]any
	for _, algo := range a.api.algorithms {
		if isRelease, _ := algo["isRelease"].(float64); isRelease == 1 {
			released = append(released, algo)
		}
	}
	return PublishedAlgosResult{Algos: released, Count: len(released)}
}

// StartRepublish 启动重发布任务（异步执行，通过 log:republish 事件推送日志）。
// 对已发布算法逐个执行：取消发布 → 等待1秒 → 重新发布。
func (a *App) StartRepublish() PublishStartResult {
	if a.api == nil {
		return PublishStartResult{Error: "请先连接平台"}
	}

	go func() {
		var released []map[string]any
		for _, algo := range a.api.algorithms {
			if isRelease, _ := algo["isRelease"].(float64); isRelease == 1 {
				released = append(released, algo)
			}
		}

		total := len(released)
		a.emitLog("republish", "============================================================")
		a.emitLog("republish", "开始执行发布流程")
		a.emitLog("republish", "============================================================")

		for idx, algo := range released {
			name, _ := algo["zhName"].(string)
			if name == "" {
				name, _ = algo["name"].(string)
			}
			algoID, _ := algo["id"].(float64)
			cores := toInt(algo["cores"])
			resourceType := toInt(algo["resourceType"])
			replicas := toInt(algo["numReplicas"])
			cpuGpu := "CPU"
			if resourceType == 2 {
				cpuGpu = "GPU"
			}

			a.emitLog("republish", fmt.Sprintf("\n[%d/%d] ========== 开始处理: %s ==========", idx+1, total, name))
			a.emitLog("republish", fmt.Sprintf("  id=%v  %s  核数=%d  副本=%d", int(algoID), cpuGpu, cores, replicas))

			// 取消发布
			a.emitLog("republish", "  >> 取消发布...")
			if err := a.api.ReleaseAlgorithm(algoID, 0, cores, resourceType, replicas); err != nil {
				authMsg := ""
				if apiErr, ok := err.(*APIError); ok && apiErr.IsAuthError {
					authMsg = "（可能是登录已过期，请重新登录）"
				}
				a.emitLog("republish", fmt.Sprintf("  << 取消发布失败: %v %s", err, authMsg))
				continue
			}
			a.emitLog("republish", "  << 取消发布成功")

			// 等待1秒
			a.emitLog("republish", "  >> 等待 1 秒...")
			time.Sleep(1 * time.Second)
			a.emitLog("republish", "  << 等待结束")

			// 重新发布
			a.emitLog("republish", "  >> 重新发布...")
			if err := a.api.ReleaseAlgorithm(algoID, 1, cores, resourceType, replicas); err != nil {
				authMsg := ""
				if apiErr, ok := err.(*APIError); ok && apiErr.IsAuthError {
					authMsg = "（可能是登录已过期，请重新登录）"
				}
				a.emitLog("republish", fmt.Sprintf("  << 重新发布失败: %v %s", err, authMsg))
			} else {
				a.emitLog("republish", "  << 重新发布成功")
			}

			a.emitLog("republish", fmt.Sprintf("[%d/%d] ========== 处理结束 ==========", idx+1, total))
		}

		a.emitLog("republish", "\n============================================================")
		a.emitLog("republish", "全部处理完成")
		a.emitLog("republish", "============================================================")
		a.emitEvent("republish:done", nil)
	}()

	return PublishStartResult{Started: true}
}

// PickDirectory 弹出目录选择对话框。
func (a *App) PickDirectory() string {
	path, err := runtime.OpenDirectoryDialog(a.ctx, runtime.OpenDialogOptions{
		Title: "选择算法目录",
	})
	if err != nil || path == "" {
		return ""
	}
	return path
}

// PickCSVFile 弹出 CSV 文件选择对话框。
func (a *App) PickCSVFile() string {
	path, err := runtime.OpenFileDialog(a.ctx, runtime.OpenDialogOptions{
		Title: "选择 CSV 文件",
		Filters: []runtime.FileFilter{
			{DisplayName: "CSV 文件", Pattern: "*.csv"},
		},
	})
	if err != nil || path == "" {
		return ""
	}
	return path
}

// SaveCSVFile 弹出保存对话框，返回选择的保存路径。
func (a *App) SaveCSVFile(defaultName string) string {
	path, err := runtime.SaveFileDialog(a.ctx, runtime.SaveDialogOptions{
		Title:           "导出算法信息",
		DefaultFilename: defaultName,
		Filters: []runtime.FileFilter{
			{DisplayName: "CSV 文件", Pattern: "*.csv"},
		},
	})
	if err != nil || path == "" {
		return ""
	}
	return path
}
