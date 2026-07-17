package bindings

import (
	"bufio"
	"context"
	"encoding/csv"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

type StartParams struct {
	ConfigPath string  `json:"configPath"`
	Mode       string  `json:"mode"`
	CycleTime  float64 `json:"cycleTime"`
	Port       int     `json:"port"`
}

type SystemStatus struct {
	Running    bool    `json:"running"`
	PID        int     `json:"pid"`
	ConfigPath string  `json:"configPath"`
	Mode       string  `json:"mode"`
	CycleTime  float64 `json:"cycleTime"`
	Port       int     `json:"port"`
}

type BatchResult struct {
	Columns []string         `json:"columns"`
	Rows    []map[string]any `json:"rows"`
}

type SystemBinding struct {
	ctx             context.Context
	mu              sync.Mutex
	cmd             *exec.Cmd
	dataFactoryPath string
	startParams     StartParams
}

func NewSystemBinding() *SystemBinding {
	return &SystemBinding{
		dataFactoryPath: findDataFactory(),
	}
}

func (b *SystemBinding) SetContext(ctx context.Context) {
	b.ctx = ctx
}

func findDataFactory() string {
	exePath, err := os.Executable()
	if err != nil {
		return ""
	}
	exeDir := filepath.Dir(exePath)
	candidates := []string{
		filepath.Join(exeDir, "DataFactory.exe"),
		filepath.Join(exeDir, "..", "DataFactory.exe"),
		filepath.Join(exeDir, "..", "..", "DataFactory.exe"),
		filepath.Join(exeDir, "..", "..", "..", "DataFactory.exe"),
	}
	for _, p := range candidates {
		if _, err := os.Stat(p); err == nil {
			abs, _ := filepath.Abs(p)
			return abs
		}
	}
	return ""
}

func (b *SystemBinding) GetDataFactoryPath() string {
	return b.dataFactoryPath
}

func (b *SystemBinding) BrowseExe() (string, error) {
	path, err := runtime.OpenFileDialog(b.ctx, runtime.OpenDialogOptions{
		Title: "选择 DataFactory.exe",
		Filters: []runtime.FileFilter{
			{DisplayName: "可执行文件", Pattern: "*.exe"},
		},
	})
	if err != nil || path == "" {
		return b.dataFactoryPath, nil
	}
	b.dataFactoryPath = path
	return path, nil
}

func (b *SystemBinding) ListConfigs() ([]string, error) {
	if b.dataFactoryPath == "" {
		return nil, fmt.Errorf("未设置 DataFactory 路径")
	}
	dir := filepath.Join(filepath.Dir(b.dataFactoryPath), "config")
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, fmt.Errorf("无法读取 config 目录: %w", err)
	}
	var configs []string
	for _, entry := range entries {
		name := entry.Name()
		if strings.HasSuffix(name, ".yaml") || strings.HasSuffix(name, ".yml") {
			configs = append(configs, name)
		}
	}
	return configs, nil
}

func (b *SystemBinding) Start(params StartParams) error {
	b.mu.Lock()
	defer b.mu.Unlock()

	if b.cmd != nil && b.cmd.ProcessState == nil {
		return fmt.Errorf("DataFactory 已在运行中")
	}
	if b.dataFactoryPath == "" {
		return fmt.Errorf("未设置 DataFactory 路径，请先选择 DataFactory.exe")
	}

	args := []string{"-c", params.ConfigPath}
	if params.Port > 0 {
		args = append(args, "--port", fmt.Sprintf("%d", params.Port))
	}
	if params.Mode != "" {
		args = append(args, "--mode", params.Mode)
	}
	if params.CycleTime > 0 {
		args = append(args, "--cycle-time", fmt.Sprintf("%g", params.CycleTime))
	}

	cmd := exec.Command(b.dataFactoryPath, args...)
	cmd.Dir = filepath.Dir(b.dataFactoryPath)

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return err
	}

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("启动 DataFactory 失败: %w", err)
	}
	b.cmd = cmd
	b.startParams = params

	go func() {
		scanner := bufio.NewScanner(stdout)
		for scanner.Scan() {
			runtime.EventsEmit(b.ctx, "df:log", scanner.Text())
		}
	}()
	go func() {
		scanner := bufio.NewScanner(stderr)
		for scanner.Scan() {
			runtime.EventsEmit(b.ctx, "df:log", scanner.Text())
		}
	}()
	go func() {
		cmd.Wait()
		b.mu.Lock()
		b.cmd = nil
		b.mu.Unlock()
		runtime.EventsEmit(b.ctx, "df:status", SystemStatus{Running: false})
	}()

	return nil
}

func (b *SystemBinding) Stop() error {
	b.mu.Lock()
	defer b.mu.Unlock()

	if b.cmd == nil || b.cmd.Process == nil {
		return fmt.Errorf("DataFactory 未在运行")
	}
	return b.cmd.Process.Kill()
}

func (b *SystemBinding) Status() SystemStatus {
	b.mu.Lock()
	defer b.mu.Unlock()

	if b.cmd == nil || b.cmd.ProcessState != nil {
		return SystemStatus{Running: false}
	}
	return SystemStatus{
		Running:    true,
		PID:        b.cmd.Process.Pid,
		ConfigPath: b.startParams.ConfigPath,
		Mode:       b.startParams.Mode,
		CycleTime:  b.startParams.CycleTime,
		Port:       b.startParams.Port,
	}
}

func (b *SystemBinding) OpenYAMLFile() (string, error) {
	return runtime.OpenFileDialog(b.ctx, runtime.OpenDialogOptions{
		Title: "打开 YAML 配置文件",
		Filters: []runtime.FileFilter{
			{DisplayName: "YAML 文件", Pattern: "*.yaml;*.yml"},
		},
	})
}

func (b *SystemBinding) SaveYAMLFile() (string, error) {
	return runtime.SaveFileDialog(b.ctx, runtime.SaveDialogOptions{
		Title:           "保存 YAML 配置文件",
		DefaultFilename: "config.yaml",
		Filters: []runtime.FileFilter{
			{DisplayName: "YAML 文件", Pattern: "*.yaml;*.yml"},
		},
	})
}

func (b *SystemBinding) RunBatch(configPath string, cycles int) (BatchResult, error) {
	if b.dataFactoryPath == "" {
		return BatchResult{}, fmt.Errorf("未设置 DataFactory 路径")
	}
	if cycles <= 0 {
		return BatchResult{}, fmt.Errorf("周期数必须大于 0")
	}

	tmpFile := filepath.Join(filepath.Dir(b.dataFactoryPath), "_batch_export.csv")
	defer os.Remove(tmpFile)

	args := []string{"-c", configPath, "--batch", fmt.Sprintf("%d", cycles), "--export", tmpFile}
	cmd := exec.Command(b.dataFactoryPath, args...)
	cmd.Dir = filepath.Dir(b.dataFactoryPath)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return BatchResult{}, fmt.Errorf("DataFactory 运行失败: %w\n%s", err, string(output))
	}

	return parseCSV(tmpFile)
}

func (b *SystemBinding) ExportBatch(configPath string, cycles int, exportPath string) error {
	if b.dataFactoryPath == "" {
		return fmt.Errorf("未设置 DataFactory 路径")
	}
	if cycles <= 0 {
		return fmt.Errorf("周期数必须大于 0")
	}

	args := []string{"-c", configPath, "--batch", fmt.Sprintf("%d", cycles), "--export", exportPath}
	cmd := exec.Command(b.dataFactoryPath, args...)
	cmd.Dir = filepath.Dir(b.dataFactoryPath)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("DataFactory 运行失败: %w\n%s", err, string(output))
	}
	return nil
}

func parseCSV(path string) (BatchResult, error) {
	file, err := os.Open(path)
	if err != nil {
		return BatchResult{}, fmt.Errorf("读取 CSV 失败: %w", err)
	}
	defer file.Close()

	reader := csv.NewReader(file)
	headers, err := reader.Read()
	if err != nil {
		return BatchResult{}, fmt.Errorf("解析 CSV 表头失败: %w", err)
	}

	var rows []map[string]any
	rowIdx := 0
	for {
		record, err := reader.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			break
		}
		row := map[string]any{"_cycle": rowIdx}
		for i, value := range record {
			if i >= len(headers) {
				break
			}
			if f, err := strconv.ParseFloat(value, 64); err == nil {
				row[headers[i]] = f
			} else {
				row[headers[i]] = value
			}
		}
		rows = append(rows, row)
		rowIdx++
	}

	return BatchResult{
		Columns: append([]string{"_cycle"}, headers...),
		Rows:    rows,
	}, nil
}
