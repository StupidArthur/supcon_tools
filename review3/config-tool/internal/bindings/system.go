package bindings

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

// StartParams 启动 DataFactory 的参数
type StartParams struct {
	ConfigPath  string  `json:"configPath"`
	Mode        string  `json:"mode"`
	CycleTime   float64 `json:"cycleTime"`
	Port        int     `json:"port"`        // OPC UA port
	APIPort     int     `json:"apiPort"`     // HTTP API port
	APIHost     string  `json:"apiHost"`     // HTTP API host
	RuntimeName string  `json:"runtimeName"` // 运行实例名（通过 --name 传递）
	EnableOpcUa bool    `json:"enableOpcUa"` // 是否启用 OPC UA
}

// SystemStatus 系统状态
type SystemStatus struct {
	Running     bool    `json:"running"`
	APIReady    bool    `json:"apiReady"`
	PID         int     `json:"pid"`
	ConfigPath  string  `json:"configPath"`
	Mode        string  `json:"mode"`
	CycleTime   float64 `json:"cycleTime"`
	Port        int     `json:"port"`
	APIPort     int     `json:"apiPort"`
	APIHost     string  `json:"apiHost"`
	RuntimeName string  `json:"runtimeName"`
	StartedAt   string  `json:"startedAt"`
	ConfigHash  string  `json:"configHash"`
	LastError   string  `json:"lastError"`
}

// BatchResult 批量仿真结果
type BatchResult struct {
	Columns []string         `json:"columns"`
	Rows    []map[string]any `json:"rows"`
}

// commandFactory 创建命令的工厂函数（用于测试注入）
type commandFactory func(name string, arg ...string) *exec.Cmd

// readinessChecker 检查 API 是否就绪的函数（用于测试注入）
// 返回 (ready bool, instanceName string, err error)
type readinessChecker func(ctx context.Context, apiHost string, apiPort int) (bool, string, error)

// processResult 进程退出结果
type processResult struct {
	ExitCode  int
	Error     error
	RecentLog []string
}

// managedProcess 受管进程状态
type managedProcess struct {
	cmd    *exec.Cmd
	done   chan struct{} // 由唯一 Wait goroutine close
	result processResult // 在 close(done) 前写入
	ready  bool          // 仅在 SystemBinding.mu 下访问

	// stdout/stderr 收集完成信号
	stdoutDone chan struct{}
	stderrDone chan struct{}

	// 取消 ready 等待
	cancelReady   context.CancelFunc
	stopOnce      sync.Once
	stopErr       error
	stopRequested bool // 仅在 SystemBinding.mu 下访问

	// 启动时的参数
	params     StartParams
	startedAt  time.Time
	configHash string
}

// SystemBinding 系统绑定
type SystemBinding struct {
	ctx             context.Context
	mu              sync.Mutex
	proc            *managedProcess // 当前进程
	dataFactoryPath string
	lastError       string // 最近一次退出的错误（proc=nil 时仍可返回）

	// 日志收集
	logLines    []string
	maxLogLines int

	// 可注入的依赖（用于测试）
	commandFactory    commandFactory
	readinessChecker  readinessChecker
	readyPollInterval time.Duration
	readyTimeout      time.Duration
	stopTimeout       time.Duration
}

// NewSystemBinding 创建系统绑定
func NewSystemBinding() *SystemBinding {
	return &SystemBinding{
		dataFactoryPath:   findDataFactory(),
		maxLogLines:       100,
		commandFactory:    func(name string, arg ...string) *exec.Cmd { return exec.Command(name, arg...) },
		readinessChecker:  defaultReadinessChecker,
		readyPollInterval: 500 * time.Millisecond,
		readyTimeout:      10 * time.Second,
		stopTimeout:       5 * time.Second,
	}
}

// setCommandFactory 设置命令工厂（用于测试，非导出）
func (b *SystemBinding) setCommandFactory(factory commandFactory) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.commandFactory = factory
}

// setReadinessChecker 设置 readiness checker（用于测试，非导出）
func (b *SystemBinding) setReadinessChecker(checker readinessChecker) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.readinessChecker = checker
}

// setReadyPollInterval 设置 ready 轮询周期（用于测试，非导出）
func (b *SystemBinding) setReadyPollInterval(d time.Duration) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.readyPollInterval = d
}

// setReadyTimeout 设置 ready 超时（用于测试，非导出）
func (b *SystemBinding) setReadyTimeout(d time.Duration) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.readyTimeout = d
}

// setStopTimeout 设置 stop 超时（用于测试，非导出）
func (b *SystemBinding) setStopTimeout(d time.Duration) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.stopTimeout = d
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

// GetDataFactoryPath 获取 DataFactory 路径
func (b *SystemBinding) GetDataFactoryPath() string {
	return b.dataFactoryPath
}

// BrowseExe 浏览选择 DataFactory.exe
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

// ListConfigs 列出配置文件
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

// BuildArgs 构建命令行参数（纯函数，便于测试）
func BuildArgs(params StartParams) []string {
	args := []string{"-c", params.ConfigPath}

	if params.Mode != "" {
		args = append(args, "--mode", params.Mode)
	}
	if params.CycleTime > 0 {
		args = append(args, "--cycle-time", fmt.Sprintf("%g", params.CycleTime))
	}
	// OPC UA port：standalone_main.py 不支持关闭 OPC UA，始终传递 port
	if params.Port > 0 {
		args = append(args, "--port", fmt.Sprintf("%d", params.Port))
	}

	// API 参数
	args = append(args, "--api")
	if params.APIHost != "" {
		args = append(args, "--api-host", params.APIHost)
	}
	if params.APIPort > 0 {
		args = append(args, "--api-port", fmt.Sprintf("%d", params.APIPort))
	}
	if params.RuntimeName != "" {
		args = append(args, "--name", params.RuntimeName)
	}

	return args
}

// Start 启动 DataFactory 并等待 API ready
// 只有在 API 真正 ready 且 instance_name 匹配后才返回成功
func (b *SystemBinding) Start(params StartParams) error {
	b.mu.Lock()
	if b.proc != nil {
		b.mu.Unlock()
		return fmt.Errorf("DataFactory 已在运行中")
	}
	if b.dataFactoryPath == "" {
		b.mu.Unlock()
		return fmt.Errorf("未设置 DataFactory 路径，请先选择 DataFactory.exe")
	}

	// 从检查到 cmd.Start/proc 注册始终持锁。这样并发 Start 不能越过检查，
	// Cleanup/Stop 也不会在“进程已启动但尚未注册”的窗口错误返回。
	hash, err := fileHashSHA256(params.ConfigPath)
	if err != nil {
		b.mu.Unlock()
		return fmt.Errorf("无法读取配置文件: %w", err)
	}
	commandFactory := b.commandFactory
	readinessChecker := b.readinessChecker
	pollInterval := b.readyPollInterval
	readyTimeout := b.readyTimeout
	dataFactoryPath := b.dataFactoryPath
	args := BuildArgs(params)
	cmd := commandFactory(dataFactoryPath, args...)
	cmd.Dir = filepath.Dir(dataFactoryPath)

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		b.mu.Unlock()
		return fmt.Errorf("创建 stdout 管道失败: %w", err)
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		b.mu.Unlock()
		return fmt.Errorf("创建 stderr 管道失败: %w", err)
	}

	if err := cmd.Start(); err != nil {
		b.mu.Unlock()
		return fmt.Errorf("启动 DataFactory 失败: %w", err)
	}

	readyCtx, cancelReady := context.WithTimeout(context.Background(), readyTimeout)
	proc := &managedProcess{
		cmd:         cmd,
		done:        make(chan struct{}),
		stdoutDone:  make(chan struct{}),
		stderrDone:  make(chan struct{}),
		cancelReady: cancelReady,
		params:      params,
		startedAt:   time.Now(),
		configHash:  hash,
	}
	b.proc = proc
	b.lastError = ""
	b.logLines = nil
	b.mu.Unlock()

	go b.collectLogs(stdout, proc.stdoutDone)
	go b.collectLogs(stderr, proc.stderrDone)
	go b.monitorProcess(proc)

	apiHost := params.APIHost
	if apiHost == "" {
		apiHost = "127.0.0.1"
	}
	apiPort := params.APIPort
	if apiPort <= 0 {
		apiPort = 8000
	}
	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()
	defer cancelReady()

	for {
		select {
		case <-readyCtx.Done():
			_ = b.terminateProcess(proc, false)
			reason := "API ready 超时"
			if readyCtx.Err() == context.Canceled {
				reason = "启动已取消"
			}
			b.mu.Lock()
			if proc.stopRequested {
				b.mu.Unlock()
				return fmt.Errorf("启动已取消")
			}
			recentLog := b.getRecentLogsLocked()
			b.lastError = fmt.Sprintf("%s; 最近日志: %v", reason, recentLog)
			lastErr := b.lastError
			b.mu.Unlock()
			return fmt.Errorf("%s", lastErr)

		case <-proc.done:
			result := proc.result
			errMsg := fmt.Sprintf("进程提前退出，exit code: %d", result.ExitCode)
			if result.Error != nil {
				errMsg += fmt.Sprintf("; %v", result.Error)
			}
			errMsg += fmt.Sprintf("; 最近日志: %v", result.RecentLog)
			return fmt.Errorf(errMsg)

		case <-ticker.C:
			ready, instanceName, err := readinessChecker(readyCtx, apiHost, apiPort)
			if err != nil {
				continue
			}
			if !ready {
				continue
			}

			if instanceName != params.RuntimeName {
				_ = b.terminateProcess(proc, false)
				b.mu.Lock()
				recentLog := b.getRecentLogsLocked()
				b.lastError = fmt.Sprintf("instance_name 不匹配: 期望 %q, 实际 %q; 最近日志: %v",
					params.RuntimeName, instanceName, recentLog)
				lastErr := b.lastError
				b.mu.Unlock()
				return fmt.Errorf("%s", lastErr)
			}

			b.mu.Lock()
			if b.proc != proc {
				b.mu.Unlock()
				return fmt.Errorf("启动已取消")
			}
			select {
			case <-proc.done:
				result := proc.result
				b.mu.Unlock()
				return fmt.Errorf("进程在 ready 确认时退出，exit code: %d", result.ExitCode)
			default:
				proc.ready = true
			}
			status := b.buildStatus()
			b.mu.Unlock()
			if b.ctx != nil {
				runtime.EventsEmit(b.ctx, "df:status", status)
			}
			return nil
		}
	}
}

// monitorProcess 唯一的进程监控 goroutine
func (b *SystemBinding) monitorProcess(proc *managedProcess) {
	err := proc.cmd.Wait()
	exitCode := 0
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
		}
	}

	<-proc.stdoutDone
	<-proc.stderrDone

	proc.result = processResult{
		ExitCode:  exitCode,
		Error:     err,
		RecentLog: b.GetRecentLogs(),
	}
	close(proc.done)

	b.mu.Lock()
	isCurrent := b.proc == proc
	if isCurrent {
		if proc.stopRequested {
			b.lastError = ""
		} else {
			b.lastError = formatProcessError(proc.result)
		}
		b.proc = nil
	}
	b.mu.Unlock()

	// 发送事件
	if isCurrent {
		status := b.Status()
		if b.ctx != nil {
			runtime.EventsEmit(b.ctx, "df:status", status)
			runtime.EventsEmit(b.ctx, "df:exited", map[string]any{
				"exitCode": exitCode,
				"error":    err,
			})
		}
	}
}

// terminateProcess 终止进程
func (b *SystemBinding) terminateProcess(proc *managedProcess, expectedStop bool) error {
	b.mu.Lock()
	if expectedStop {
		proc.stopRequested = true
	}
	stopTimeout := b.stopTimeout
	b.mu.Unlock()

	proc.cancelReady()
	proc.stopOnce.Do(func() {
		select {
		case <-proc.done:
			return
		default:
		}

		if proc.cmd.Process == nil {
			proc.stopErr = fmt.Errorf("受管进程句柄不存在")
			return
		}

		if err := proc.cmd.Process.Signal(os.Interrupt); err != nil {
			// Windows 通常不支持 os.Interrupt；此时立即 Kill，不等待无意义的超时。
			if killErr := proc.cmd.Process.Kill(); killErr != nil {
				select {
				case <-proc.done:
					return
				default:
					proc.stopErr = fmt.Errorf("发送 Interrupt 失败 (%v)，Kill 也失败: %w", err, killErr)
					return
				}
			}
			if !waitForDone(proc.done, stopTimeout) {
				proc.stopErr = fmt.Errorf("Kill 后进程未在 %s 内退出", stopTimeout)
			}
			return
		}

		if waitForDone(proc.done, stopTimeout) {
			return
		}
		if err := proc.cmd.Process.Kill(); err != nil {
			select {
			case <-proc.done:
				return
			default:
				proc.stopErr = fmt.Errorf("优雅停止超时且 Kill 失败: %w", err)
				return
			}
		}
		if !waitForDone(proc.done, stopTimeout) {
			proc.stopErr = fmt.Errorf("强制 Kill 后进程未在 %s 内退出", stopTimeout)
		}
	})
	return proc.stopErr
}

func waitForDone(done <-chan struct{}, timeout time.Duration) bool {
	select {
	case <-done:
		return true
	case <-time.After(timeout):
		return false
	}
}

// collectLogs 收集日志
func (b *SystemBinding) collectLogs(pipe io.Reader, done chan struct{}) {
	defer close(done)
	scanner := bufio.NewScanner(pipe)
	for scanner.Scan() {
		line := scanner.Text()
		b.mu.Lock()
		b.logLines = append(b.logLines, line)
		if len(b.logLines) > b.maxLogLines {
			b.logLines = b.logLines[1:]
		}
		b.mu.Unlock()
		if b.ctx != nil {
			runtime.EventsEmit(b.ctx, "df:log", line)
		}
	}
}

// GetRecentLogs 获取最近的日志
func (b *SystemBinding) GetRecentLogs() []string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.getRecentLogsLocked()
}

// getRecentLogsLocked 获取最近的日志（需要持有锁）
func (b *SystemBinding) getRecentLogsLocked() []string {
	result := make([]string, len(b.logLines))
	copy(result, b.logLines)
	return result
}

// Stop 停止 DataFactory
func (b *SystemBinding) Stop() error {
	b.mu.Lock()
	proc := b.proc
	if proc == nil {
		b.mu.Unlock()
		return fmt.Errorf("DataFactory 未在运行")
	}
	b.mu.Unlock()

	if err := b.terminateProcess(proc, true); err != nil {
		return err
	}

	// 清理状态
	b.mu.Lock()
	if b.proc == proc {
		b.proc = nil
	}
	b.mu.Unlock()

	// 发送事件
	status := b.Status()
	if b.ctx != nil {
		runtime.EventsEmit(b.ctx, "df:status", status)
	}
	return nil
}

// Status 获取系统状态
func (b *SystemBinding) Status() SystemStatus {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buildStatus()
}

// buildStatus 构建状态（需要持有锁）
func (b *SystemBinding) buildStatus() SystemStatus {
	proc := b.proc
	if proc == nil {
		return SystemStatus{
			Running:   false,
			LastError: b.lastError,
		}
	}

	// 检查进程是否已退出
	select {
	case <-proc.done:
		// 进程已退出
		lastErr := formatProcessError(proc.result)
		return SystemStatus{
			Running:   false,
			LastError: lastErr,
		}
	default:
		// 进程仍在运行
		return SystemStatus{
			Running:     true,
			APIReady:    proc.ready, // 读取 proc.ready，禁止硬编码 true
			PID:         proc.cmd.Process.Pid,
			ConfigPath:  proc.params.ConfigPath,
			Mode:        proc.params.Mode,
			CycleTime:   proc.params.CycleTime,
			Port:        proc.params.Port,
			APIPort:     proc.params.APIPort,
			APIHost:     proc.params.APIHost,
			RuntimeName: proc.params.RuntimeName,
			StartedAt:   proc.startedAt.Format(time.RFC3339),
			ConfigHash:  proc.configHash,
		}
	}
}

// formatProcessError 格式化进程错误
func formatProcessError(result processResult) string {
	message := fmt.Sprintf("进程意外退出，exit code: %d", result.ExitCode)
	if result.Error != nil {
		message += fmt.Sprintf("; %v", result.Error)
	}
	return fmt.Sprintf("%s; 日志: %v", message, result.RecentLog)
}

// Cleanup 清理子进程（用于 Wails OnShutdown）
func (b *SystemBinding) Cleanup() {
	b.mu.Lock()
	proc := b.proc
	b.mu.Unlock()

	if proc == nil {
		return
	}

	_ = b.terminateProcess(proc, true)

	// 清理状态
	b.mu.Lock()
	if b.proc == proc {
		b.proc = nil
	}
	b.mu.Unlock()
}

// OpenYAMLFile 打开 YAML 文件对话框
func (b *SystemBinding) OpenYAMLFile() (string, error) {
	return runtime.OpenFileDialog(b.ctx, runtime.OpenDialogOptions{
		Title: "打开 YAML 配置文件",
		Filters: []runtime.FileFilter{
			{DisplayName: "YAML 文件", Pattern: "*.yaml;*.yml"},
		},
	})
}

// SaveYAMLFile 保存 YAML 文件对话框
func (b *SystemBinding) SaveYAMLFile() (string, error) {
	return runtime.SaveFileDialog(b.ctx, runtime.SaveDialogOptions{
		Title:           "保存 YAML 配置文件",
		DefaultFilename: "config.yaml",
		Filters: []runtime.FileFilter{
			{DisplayName: "YAML 文件", Pattern: "*.yaml;*.yml"},
		},
	})
}

// RunBatch 运行批量仿真
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
	cmd := b.commandFactory(b.dataFactoryPath, args...)
	cmd.Dir = filepath.Dir(b.dataFactoryPath)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return BatchResult{}, fmt.Errorf("DataFactory 运行失败: %w\n%s", err, string(output))
	}

	return parseCSV(tmpFile)
}

// ExportBatch 导出批量仿真结果
func (b *SystemBinding) ExportBatch(configPath string, cycles int, exportPath string) error {
	if b.dataFactoryPath == "" {
		return fmt.Errorf("未设置 DataFactory 路径")
	}
	if cycles <= 0 {
		return fmt.Errorf("周期数必须大于 0")
	}

	args := []string{"-c", configPath, "--batch", fmt.Sprintf("%d", cycles), "--export", exportPath}
	cmd := b.commandFactory(b.dataFactoryPath, args...)
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

// fileHashSHA256 计算文件 SHA-256 hash
func fileHashSHA256(path string) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	hash := sha256.Sum256(data)
	return hex.EncodeToString(hash[:]), nil
}

// StatusResponse /api/status 的响应结构
type StatusResponse struct {
	InstanceName string `json:"instance_name"`
}

// ParseStatusResponse 解析 /api/status 响应
func ParseStatusResponse(data []byte) (*StatusResponse, error) {
	var resp StatusResponse
	if err := json.Unmarshal(data, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// defaultReadinessChecker 默认的 readiness checker
func defaultReadinessChecker(ctx context.Context, apiHost string, apiPort int) (bool, string, error) {
	url := fmt.Sprintf("http://%s:%d/api/status", apiHost, apiPort)
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return false, "", err
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return false, "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return false, "", nil
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return false, "", err
	}

	statusResp, err := ParseStatusResponse(body)
	if err != nil {
		return false, "", err
	}

	return true, statusResp.InstanceName, nil
}
