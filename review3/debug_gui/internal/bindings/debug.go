package bindings

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"debug-gui/internal/api"
	"debug-gui/internal/engine"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

// StartParams 是启动引擎的参数
type StartParams struct {
	WorkDir    string  `json:"workDir"`    // review3 目录（含 standalone_main.py）
	PythonPath string  `json:"pythonPath"` // python.exe 路径（空则从 PATH 查找）
	ConfigPath string  `json:"configPath"` // YAML 配置文件路径
	Mode       string  `json:"mode"`
	CycleTime  float64 `json:"cycleTime"`
	Port       int     `json:"port"`
}

// BatchParams 是批量仿真的参数
type BatchParams struct {
	WorkDir    string  `json:"workDir"`
	PythonPath string  `json:"pythonPath"`
	ConfigPath string  `json:"configPath"`
	Cycles     int     `json:"cycles"`
	CycleTime  float64 `json:"cycleTime"`
}

// EngineStatus 返回引擎状态
type EngineStatus struct {
	Running    bool   `json:"running"`
	PID        int    `json:"pid"`
	ConfigPath string `json:"configPath"`
	Mode       string `json:"mode"`
	Port       int    `json:"port"`
}

// DebugBinding 暴露给前端 JS 的调试接口
type DebugBinding struct {
	ctx       context.Context
	proc      *engine.EngineProc
	lastStart StartParams
}

func NewDebugBinding() *DebugBinding {
	return &DebugBinding{
		proc: engine.NewEngineProc(),
	}
}

func (b *DebugBinding) SetContext(ctx context.Context) {
	b.ctx = ctx
	b.proc.SetContext(ctx)
}

// BrowseDir 打开目录选择对话框（选择 review3 目录）
func (b *DebugBinding) BrowseDir(title string) (string, error) {
	path, err := runtime.OpenDirectoryDialog(b.ctx, runtime.OpenDialogOptions{
		Title: title,
	})
	if err != nil || path == "" {
		return "", nil
	}
	return path, nil
}

// BrowseExe 打开文件选择对话框，选择 python.exe
func (b *DebugBinding) BrowseExe() (string, error) {
	path, err := runtime.OpenFileDialog(b.ctx, runtime.OpenDialogOptions{
		Title: "选择 python.exe（可跳过，从 PATH 查找）",
		Filters: []runtime.FileFilter{
			{DisplayName: "可执行文件", Pattern: "*.exe"},
		},
	})
	if err != nil || path == "" {
		return "", nil
	}
	return path, nil
}

// BrowseYAML 打开文件选择对话框，选择 YAML 配置文件
func (b *DebugBinding) BrowseYAML() (string, error) {
	path, err := runtime.OpenFileDialog(b.ctx, runtime.OpenDialogOptions{
		Title: "选择 YAML 配置文件",
		Filters: []runtime.FileFilter{
			{DisplayName: "YAML 文件", Pattern: "*.yaml;*.yml"},
		},
	})
	if err != nil || path == "" {
		return "", nil
	}
	return path, nil
}

// SaveCSVFile 打开保存对话框，选择 CSV 导出路径
func (b *DebugBinding) SaveCSVFile() (string, error) {
	path, err := runtime.SaveFileDialog(b.ctx, runtime.SaveDialogOptions{
		Title:           "导出 CSV 文件",
		DefaultFilename: "export.csv",
		Filters: []runtime.FileFilter{
			{DisplayName: "CSV 文件", Pattern: "*.csv"},
		},
	})
	if err != nil || path == "" {
		return "", nil
	}
	return path, nil
}

// ListConfigs 扫描 workDir/config/ 目录，返回 YAML 文件列表
func (b *DebugBinding) ListConfigs(workDir string) ([]string, error) {
	if workDir == "" {
		return nil, fmt.Errorf("未设置工作目录")
	}
	return api.ListConfigs(workDir)
}

// ParseYAMLConfig 解析 YAML 配置文件
func (b *DebugBinding) ParseYAMLConfig(yamlPath string) (api.YAMLConfig, error) {
	return api.ParseYAML(yamlPath)
}

// StartEngine 启动实时+OPC UA 模式
func (b *DebugBinding) StartEngine(params StartParams) (EngineStatus, error) {
	if params.WorkDir == "" {
		return EngineStatus{}, fmt.Errorf("未设置工作目录")
	}
	if params.ConfigPath == "" {
		return EngineStatus{}, fmt.Errorf("未选择配置文件")
	}

	pid, err := b.proc.StartRealtime(
		params.WorkDir, params.PythonPath, params.ConfigPath,
		params.Mode, params.CycleTime, params.Port,
	)
	if err != nil {
		return EngineStatus{}, err
	}

	b.lastStart = params
	return EngineStatus{
		Running:    true,
		PID:        pid,
		ConfigPath: params.ConfigPath,
		Mode:       params.Mode,
		Port:       params.Port,
	}, nil
}

// StartBatch 启动批量仿真模式
func (b *DebugBinding) StartBatch(params BatchParams) (string, error) {
	if params.WorkDir == "" {
		return "", fmt.Errorf("未设置工作目录")
	}
	if params.ConfigPath == "" {
		return "", fmt.Errorf("未选择配置文件")
	}
	if params.Cycles <= 0 {
		return "", fmt.Errorf("周期数必须大于 0")
	}

	tmpFile := filepath.Join(params.WorkDir, "_batch_export.csv")

	err := b.proc.StartBatch(
		params.WorkDir, params.PythonPath, params.ConfigPath,
		params.Cycles, params.CycleTime, tmpFile,
	)
	if err != nil {
		return "", err
	}

	b.lastStart = StartParams{
		WorkDir:    params.WorkDir,
		PythonPath: params.PythonPath,
		ConfigPath: params.ConfigPath,
		Mode:       "GENERATOR",
		CycleTime:  params.CycleTime,
	}
	return tmpFile, nil
}

// ReadBatchResult 读取批量仿真产出的 CSV 文件
func (b *DebugBinding) ReadBatchResult(csvPath string) (api.BatchResult, error) {
	return api.ParseCSV(csvPath)
}

// ExportBatch 运行批量仿真并导出到指定路径
func (b *DebugBinding) ExportBatch(params BatchParams, exportPath string) error {
	if params.WorkDir == "" {
		return fmt.Errorf("未设置工作目录")
	}
	if params.Cycles <= 0 {
		return fmt.Errorf("周期数必须大于 0")
	}

	return b.proc.StartBatch(
		params.WorkDir, params.PythonPath, params.ConfigPath,
		params.Cycles, params.CycleTime, exportPath,
	)
}

// StopEngine 停止引擎
func (b *DebugBinding) StopEngine() error {
	return b.proc.Stop()
}

// GetStatus 返回引擎状态
func (b *DebugBinding) GetStatus() EngineStatus {
	if !b.proc.IsRunning() {
		return EngineStatus{Running: false}
	}
	return EngineStatus{
		Running:    true,
		ConfigPath: b.lastStart.ConfigPath,
		Mode:       b.lastStart.Mode,
		Port:       b.lastStart.Port,
	}
}

// CleanupTempFile 清理临时 CSV 文件
func (b *DebugBinding) CleanupTempFile(path string) {
	if path != "" {
		os.Remove(path)
	}
}

// GetDefaultWorkDir 根据 exe 所在位置推断 review3 工作目录
// exe 位于 review3/debug_gui/build/bin/，review3 在往上三级
func (b *DebugBinding) GetDefaultWorkDir() string {
	exe, err := os.Executable()
	if err != nil {
		return ""
	}
	exeDir := filepath.Dir(exe)
	candidates := []string{
		filepath.Join(exeDir, "..", "..", ".."), // build/bin -> debug_gui -> review3
		filepath.Join(exeDir, "..", ".."),       // bin -> debug_gui
		exeDir,
	}
	for _, c := range candidates {
		abs, err := filepath.Abs(c)
		if err != nil {
			continue
		}
		if _, err := os.Stat(filepath.Join(abs, "standalone_main.py")); err == nil {
			return abs
		}
	}
	return ""
}

// ReadYAMLContent 读取 YAML 配置文件的原始文本内容
func (b *DebugBinding) ReadYAMLContent(path string) (string, error) {
	if path == "" {
		return "", fmt.Errorf("未指定文件路径")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("读取文件失败: %w", err)
	}
	return string(data), nil
}

// WriteYAMLContent 将文本内容写回 YAML 配置文件
func (b *DebugBinding) WriteYAMLContent(path string, content string) error {
	if path == "" {
		return fmt.Errorf("未指定文件路径")
	}
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		return fmt.Errorf("写入文件失败: %w", err)
	}
	return nil
}
