package bindings

import (
	"bufio"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"config-tool/internal/config"

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
	APIToken    string  `json:"-"`           // 本地 API 会话令牌（不暴露给前端）
}

// SystemStatus 系统状态
type SystemStatus struct {
	Running       bool    `json:"running"`
	APIReady      bool    `json:"apiReady"`
	PID           int     `json:"pid"`
	ConfigPath    string  `json:"configPath"`
	Mode          string  `json:"mode"`
	CycleTime     float64 `json:"cycleTime"`
	Port          int     `json:"port"`
	APIPort       int     `json:"apiPort"`
	APIHost       string  `json:"apiHost"`
	RuntimeName   string  `json:"runtimeName"`
	StartedAt     string  `json:"startedAt"`
	ConfigHash    string  `json:"configHash"`
	LastError     string  `json:"lastError"`
	BatchRunning  bool    `json:"batchRunning"`
	ActiveBatches int     `json:"activeBatches"`
}

// BatchResult 批量仿真结果
type BatchResult struct {
	Columns []string         `json:"columns"`
	Rows    []map[string]any `json:"rows"`
	// DisplayColumns 是 DSL display_args 声明的默认绘图列（来自引擎 get_display_variables），
	// 已过滤为 Columns 中实际存在的列；YAML 未写 display_args 时为空。
	DisplayColumns []string `json:"displayColumns"`
	// PlotScales 是 DSL display_args 中声明的绘图缩放（[ref]），
	// 计算规则：plotValue = raw × 100 / ref。仅保留 CSV 中实际存在、有限且 ref > 0 的列；
	// sidecar 缺失/损坏或字段非法时为空，不阻断 Batch。
	PlotScales map[string]float64 `json:"plotScales"`
}

// commandFactory 创建命令的工厂函数（用于测试注入）
type commandFactory func(name string, arg ...string) *exec.Cmd

// readinessChecker 检查 API 是否就绪的函数（用于测试注入）。
// token 允许为空（开发环境 / DATAFACTORY_NO_AUTH），但生产模式下应始终提供；
// checker 自身负责把 token 写入 Authorization header，不依赖外部全局状态。
// 返回 (ready bool, instanceName string, err error)。
type readinessChecker func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error)

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
	activeBatches   int             // 当前进行中的批量任务数（受 mu 保护）
	dataFactoryPath string
	dfLaunch        dataFactoryExec
	lastError       string // 最近一次退出的错误（proc=nil 时仍可返回）

	// 日志收集
	logLines    []string
	maxLogLines int

	// 进程退出监听器（notifyOnExit 回调列表）。在 monitorProcess 检测到进程退出时调用，
	// 监听器逻辑必须轻量、非阻塞；用于 RealtimeRuntimeBinding 清理 session。
	exitMu       sync.Mutex
	exitListeners []func(exitCode int, normalStop bool)

	// 可注入的依赖（用于测试）
	commandFactory    commandFactory
	readinessChecker  readinessChecker
	readyPollInterval time.Duration
	readyTimeout      time.Duration
	stopTimeout       time.Duration
	// terminateErrorOverride 仅用于测试：强制 Stop() 返回指定 error，
	// 同时保持 Status().Running=true（不修改 b.proc 状态）。
	// 生产代码不要设置此字段。
	terminateErrorOverride error
}

// NewSystemBinding 创建系统绑定
func NewSystemBinding() *SystemBinding {
	launch, _ := resolveDataFactoryLaunch()
	return &SystemBinding{
		dataFactoryPath:   launch.displayPath(),
		dfLaunch:          launch,
		maxLogLines:       100,
		commandFactory:    func(name string, arg ...string) *exec.Cmd { return exec.Command(name, arg...) },
		readinessChecker:  defaultReadinessChecker,
		readyPollInterval: 500 * time.Millisecond,
		readyTimeout:      10 * time.Second,
		stopTimeout:       5 * time.Second,
	}
}

// addExitListener 注册进程退出回调（私有 API，绑定包内部使用）。
// 当前 process 退出时（任意原因）调用。回调在持有 monitorProcess 同一
// goroutine 内调用；必须非阻塞。返回值：可用于注销的句柄。
//
// 不导出：避免 Wails 绑定把它暴露给前端；前端只能通过其它事件（df:exited
// / df:status / GetConnectionInfo）观察退出。
func (b *SystemBinding) addExitListener(fn func(exitCode int, normalStop bool)) func() {
	b.exitMu.Lock()
	defer b.exitMu.Unlock()
	b.exitListeners = append(b.exitListeners, fn)
	i := len(b.exitListeners) - 1
	return func() {
		b.exitMu.Lock()
		defer b.exitMu.Unlock()
		if i < len(b.exitListeners) {
			b.exitListeners[i] = func(exitCode int, normalStop bool) {}
		}
	}
}

func (b *SystemBinding) dispatchExit(exitCode int, normalStop bool) {
	b.exitMu.Lock()
	listeners := make([]func(exitCode int, normalStop bool), len(b.exitListeners))
	copy(listeners, b.exitListeners)
	b.exitMu.Unlock()
	for _, fn := range listeners {
		if fn == nil {
			continue
		}
		func() {
			defer func() {
				_ = recover() // 监听器 panic 必须不影响 monitorProcess
			}()
			fn(exitCode, normalStop)
		}()
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
	launch, err := resolveDataFactoryLaunch()
	if err != nil {
		return ""
	}
	return launch.displayPath()
}

func (b *SystemBinding) ensureDataFactory() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.ensureDataFactoryLocked()
}

func (b *SystemBinding) ensureDataFactoryLocked() error {
	if b.dfLaunch.valid() {
		return nil
	}
	if strings.TrimSpace(b.dataFactoryPath) != "" {
		exe := strings.Fields(b.dataFactoryPath)[0]
		b.dfLaunch = dataFactoryExec{exe: exe, workDir: filepath.Dir(exe)}
		return nil
	}
	launch, err := resolveDataFactoryLaunch()
	if err != nil {
		return err
	}
	b.dfLaunch = launch
	b.dataFactoryPath = launch.displayPath()
	return nil
}

// GetDataFactoryPath 获取 DataFactory 路径
func (b *SystemBinding) GetDataFactoryPath() string {
	if err := b.ensureDataFactory(); err == nil {
		return b.dataFactoryPath
	}
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
	b.dfLaunch = dataFactoryExec{exe: path, workDir: filepath.Dir(path)}
	return path, nil
}

// ListConfigs 列出配置文件
func (b *SystemBinding) ListConfigs() ([]string, error) {
	if err := b.ensureDataFactory(); err != nil {
		return nil, err
	}
	dir, err := config.ResolveConfigDir()
	if err != nil {
		dir = filepath.Join(filepath.Dir(b.dfLaunch.exe), "config")
	}
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
	if params.APIToken != "" {
		args = append(args, "--api-token", params.APIToken)
	}

	return args
}

// generateAPIToken 生成本次运行的随机会话令牌（仅内存，不落盘、不入日志）。
func generateAPIToken() string {
	buf := make([]byte, 24)
	if _, err := rand.Read(buf); err != nil {
		return fmt.Sprintf("tok-%d", time.Now().UnixNano())
	}
	return hex.EncodeToString(buf)
}

// beginBatch 获取批量任务 lease：实时进程运行中或已有批量任务运行时拒绝，否则 activeBatches++。
// 同一时间最多允许一个批量任务。调用方必须用 defer endBatch()，失败路径也要释放。
func (b *SystemBinding) beginBatch() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.proc != nil {
		return fmt.Errorf("实时仿真正在运行，无法执行批量任务")
	}
	if b.activeBatches > 0 {
		return fmt.Errorf("已有批量任务正在运行，禁止并发批量任务")
	}
	b.activeBatches++
	return nil
}

// endBatch 释放批量任务 lease。
func (b *SystemBinding) endBatch() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.activeBatches--
}

// Start 启动 DataFactory 并等待 API ready
// 只有在 API 真正 ready 且 instance_name 匹配后才返回成功
func (b *SystemBinding) Start(params StartParams) error {
	b.mu.Lock()
	if b.proc != nil {
		b.mu.Unlock()
		return fmt.Errorf("DataFactory 已在运行中")
	}
	if err := b.ensureDataFactoryLocked(); err != nil {
		b.mu.Unlock()
		return fmt.Errorf("未设置 DataFactory 路径，请先选择 DataFactory.exe")
	}
	if b.activeBatches > 0 {
		b.mu.Unlock()
		return fmt.Errorf("批量任务正在运行，无法启动实时仿真")
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
	dfLaunch := b.dfLaunch
	if params.APIToken == "" {
		params.APIToken = generateAPIToken()
	}
	// publish token before we touch any subprocess state; rollback in defer below
	// covers every failure path (pipe / start / ready / instance mismatch / early exit).
	SetCurrentAPIToken(params.APIToken)
	tokenCommitted := true
	defer func() {
		if tokenCommitted {
			SetCurrentAPIToken("")
		}
	}()
	args := BuildArgs(params)
	cmd := dfLaunch.command(commandFactory, args...)

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
			ready, instanceName, err := readinessChecker(readyCtx, apiHost, apiPort, params.APIToken)
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
			// token stays valid for the lifetime of this process; cleared on Stop / unexpected exit.
			tokenCommitted = false
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
	normalStop := proc.stopRequested
	if isCurrent {
		if normalStop {
			b.lastError = ""
		} else {
			b.lastError = formatProcessError(proc.result)
		}
		b.proc = nil
	}
	b.mu.Unlock()

	// 进程退出（正常或异常）→ 当前 token 立即失效，避免泄漏给无效监听端。
	if isCurrent {
		SetCurrentAPIToken("")
	}

	// 通知会话层监听器：先于事件 emit，保证监听器先把 session 状态清干净。
	if isCurrent {
		b.dispatchExit(exitCode, normalStop)
	}

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
	override := b.terminateErrorOverride
	b.mu.Unlock()

	if override != nil {
		// 测试 hook：直接返回 override，进程仍 Running。
		proc.stopErr = override
		proc.cancelReady()
		return override
	}

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

	// 运行结束，会话令牌立即失效
	SetCurrentAPIToken("")

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
	var st SystemStatus
	proc := b.proc
	switch {
	case proc == nil:
		st = SystemStatus{Running: false, LastError: b.lastError}
	default:
		select {
		case <-proc.done:
			// 进程已退出
			st = SystemStatus{Running: false, LastError: formatProcessError(proc.result)}
		default:
			// 进程仍在运行
			st = SystemStatus{
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
	st.BatchRunning = b.activeBatches > 0
	st.ActiveBatches = b.activeBatches
	return st
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

// WriteTextFile 将 UTF-8 文本写入指定路径（通用 YAML 保存）。
func (b *SystemBinding) WriteTextFile(path string, content string) error {
	if strings.TrimSpace(path) == "" {
		return fmt.Errorf("路径不能为空")
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(abs), 0o755); err != nil {
		return fmt.Errorf("创建目录失败: %w", err)
	}
	tmp, err := os.CreateTemp(filepath.Dir(abs), ".dsl-write-*.tmp")
	if err != nil {
		return fmt.Errorf("创建临时文件失败: %w", err)
	}
	tmpPath := tmp.Name()
	defer func() {
		if _, statErr := os.Stat(tmpPath); statErr == nil {
			_ = os.Remove(tmpPath)
		}
	}()
	if _, err := tmp.Write([]byte(content)); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmpPath, abs)
}

// CleanupTempYAML 清理 WriteTempYAML / AllocateTempYAMLPath 产生的临时目录。
func (b *SystemBinding) CleanupTempYAML(path string) error {
	if strings.TrimSpace(path) == "" {
		return fmt.Errorf("路径不能为空")
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	dir := filepath.Dir(abs)
	base := filepath.Base(dir)
	if !strings.HasPrefix(base, "review3-draft-sim-") {
		return fmt.Errorf("拒绝清理非 draft 临时目录: %s", base)
	}
	return os.RemoveAll(dir)
}

// ExportCSVRows 将内存中的仿真结果写入用户选择的 CSV（不重新跑 Batch）。
func (b *SystemBinding) ExportCSVRows(columns []string, rows []map[string]any, exportPath string) error {
	if strings.TrimSpace(exportPath) == "" {
		return fmt.Errorf("导出路径不能为空")
	}
	if len(columns) == 0 {
		return fmt.Errorf("列为空，无法导出")
	}
	abs, err := filepath.Abs(exportPath)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(abs), 0o755); err != nil {
		return fmt.Errorf("创建目录失败: %w", err)
	}
	f, err := os.Create(abs)
	if err != nil {
		return fmt.Errorf("创建 CSV 失败: %w", err)
	}
	defer f.Close()

	w := csv.NewWriter(f)
	if err := w.Write(columns); err != nil {
		return fmt.Errorf("写表头失败: %w", err)
	}
	for _, row := range rows {
		record := make([]string, len(columns))
		for i, col := range columns {
			record[i] = formatCSVCell(row[col])
		}
		if err := w.Write(record); err != nil {
			return fmt.Errorf("写数据行失败: %w", err)
		}
	}
	w.Flush()
	if err := w.Error(); err != nil {
		return err
	}
	return nil
}

func formatCSVCell(v any) string {
	if v == nil {
		return ""
	}
	switch t := v.(type) {
	case string:
		return t
	case float64:
		return strconv.FormatFloat(t, 'g', -1, 64)
	case float32:
		return strconv.FormatFloat(float64(t), 'g', -1, 32)
	case int:
		return strconv.Itoa(t)
	case int64:
		return strconv.FormatInt(t, 10)
	case bool:
		if t {
			return "true"
		}
		return "false"
	default:
		return fmt.Sprint(t)
	}
}

// ReadTextFile 读取 UTF-8 文本文件（YAML 源码编辑器用）。
func (b *SystemBinding) ReadTextFile(path string) (string, error) {
	if strings.TrimSpace(path) == "" {
		return "", fmt.Errorf("路径不能为空")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	return string(data), nil
}

// WriteTempYAML 将内容写入唯一临时 YAML，返回绝对路径。
// 供「当前 draft 仿真」使用：不覆盖用户文件。
func (b *SystemBinding) WriteTempYAML(content string) (string, error) {
	dir, err := os.MkdirTemp("", "review3-draft-sim-*")
	if err != nil {
		return "", fmt.Errorf("创建临时目录失败: %w", err)
	}
	path := filepath.Join(dir, "draft.yaml")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		_ = os.RemoveAll(dir)
		return "", fmt.Errorf("写入临时 YAML 失败: %w", err)
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return path, nil
	}
	return abs, nil
}

// AllocateTempYAMLPath 分配一个尚不存在的临时 YAML 路径（目录已创建）。
// 供模板 SaveTemplate 物化 draft 到临时文件时使用。
func (b *SystemBinding) AllocateTempYAMLPath() (string, error) {
	dir, err := os.MkdirTemp("", "review3-draft-sim-*")
	if err != nil {
		return "", fmt.Errorf("创建临时目录失败: %w", err)
	}
	path := filepath.Join(dir, "draft.yaml")
	abs, err := filepath.Abs(path)
	if err != nil {
		return path, nil
	}
	return abs, nil
}

// OpenYAMLFile 打开 YAML 文件对话框
func (b *SystemBinding) OpenYAMLFile() (string, error) {
	opts := runtime.OpenDialogOptions{
		Title: "打开 YAML 配置文件",
		Filters: []runtime.FileFilter{
			{DisplayName: "YAML 文件", Pattern: "*.yaml;*.yml"},
		},
	}
	if dir, err := config.ResolveConfigDir(); err == nil {
		opts.DefaultDirectory = dir
	}
	return runtime.OpenFileDialog(b.ctx, opts)
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

// SaveCSVFile 保存 CSV 文件对话框（独立于 YAML，不复用 YAML 过滤器）
func (b *SystemBinding) SaveCSVFile() (string, error) {
	return runtime.SaveFileDialog(b.ctx, runtime.SaveDialogOptions{
		Title:           "保存 CSV 文件",
		DefaultFilename: "result.csv",
		Filters: []runtime.FileFilter{
			{DisplayName: "CSV 文件", Pattern: "*.csv"},
		},
	})
}

// exportFileDialogSpec 将导出格式解析为保存对话框参数（纯函数，便于测试）。
// 仅支持 csv/xlsx；xls 当前版本暂不支持，未知格式返回错误——都不静默落到 CSV。
func exportFileDialogSpec(format string) (displayName string, pattern string, def string, err error) {
	switch strings.ToLower(strings.TrimSpace(format)) {
	case "csv":
		return "CSV 文件", "*.csv", "result.csv", nil
	case "xlsx":
		return "Excel 工作簿 (*.xlsx)", "*.xlsx", "result.xlsx", nil
	case "xls":
		return "", "", "", fmt.Errorf("当前版本暂不支持 xls，请使用 xlsx 或 csv")
	default:
		return "", "", "", fmt.Errorf("不支持的导出格式: %s", format)
	}
}

// SaveExportFile 按导出格式弹出保存对话框（csv/xlsx）。xls 与未知格式返回明确错误。
func (b *SystemBinding) SaveExportFile(format string) (string, error) {
	displayName, pattern, def, err := exportFileDialogSpec(format)
	if err != nil {
		return "", err
	}
	return runtime.SaveFileDialog(b.ctx, runtime.SaveDialogOptions{
		Title:           "导出仿真结果",
		DefaultFilename: def,
		Filters: []runtime.FileFilter{
			{DisplayName: displayName, Pattern: pattern},
		},
	})
}

// RunBatch 运行批量仿真
func (b *SystemBinding) RunBatch(configPath string, cycles int) (BatchResult, error) {
	if err := b.ensureDataFactory(); err != nil {
		return BatchResult{}, err
	}
	if cycles <= 0 {
		return BatchResult{}, fmt.Errorf("周期数必须大于 0")
	}
	if err := b.beginBatch(); err != nil {
		return BatchResult{}, err
	}
	defer b.endBatch()

	workDir, err := os.MkdirTemp("", "review3-batch-*")
	if err != nil {
		return BatchResult{}, fmt.Errorf("创建批量临时目录失败: %w", err)
	}
	defer os.RemoveAll(workDir)
	csvPath := filepath.Join(workDir, "result.csv")

	args := []string{"-c", configPath, "--batch", fmt.Sprintf("%d", cycles), "--export", csvPath}
	cmd := b.dfLaunch.command(b.commandFactory, args...)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return BatchResult{}, fmt.Errorf("DataFactory 运行失败: %w\n%s", err, string(output))
	}

	if err := validateBatchCSV(csvPath); err != nil {
		return BatchResult{}, err
	}
	result, err := parseCSV(csvPath)
	if err != nil {
		return BatchResult{}, err
	}
	result.DisplayColumns, result.PlotScales =
		readDisplayMetadata(csvPath, result.Columns)
	return result, nil
}

// readDisplayMetadata 读取批量导出 CSV 旁的 sidecar（<csv>.display.json）。
// 返回 DSL display_args 声明的：
//   - display_columns（已过滤为 CSV 实际存在的列）
//   - plot_scales（仅保留有效列；scale 必须是有限数且 > 0，否则忽略）
//
// sidecar 缺失、JSON 损坏、字段类型错误时返回零值（nil 列 + nil map），不阻断 Batch。
// 兼容旧 sidecar 只含 display_columns 的情况。
func readDisplayMetadata(
	csvPath string,
	validColumns []string,
) ([]string, map[string]float64) {
	data, err := os.ReadFile(csvPath + ".display.json")
	if err != nil {
		return nil, nil
	}
	// 兼容旧版（只含 display_columns）与新版（含 plot_scales）的 sidecar。
	// plot_scales 解析为 interface{} 以容忍混合值（数字/字符串），按条目单独判断。
	var payload struct {
		DisplayColumns []string               `json:"display_columns"`
		PlotScales     map[string]interface{} `json:"plot_scales,omitempty"`
	}
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil, nil
	}
	valid := make(map[string]bool, len(validColumns))
	for _, c := range validColumns {
		valid[c] = true
	}
	var (
		displayColumns []string
		plotScales     map[string]float64
	)
	for _, c := range payload.DisplayColumns {
		if valid[c] {
			displayColumns = append(displayColumns, c)
		}
	}
	for k, raw := range payload.PlotScales {
		if !valid[k] {
			continue
		}
		f, ok := coercePositiveFloat(raw)
		if !ok || !isFiniteNonZeroPositive(f) {
			continue
		}
		if plotScales == nil {
			plotScales = make(map[string]float64)
		}
		plotScales[k] = f
	}
	return displayColumns, plotScales
}

// coercePositiveFloat 将 JSON 值转为 float64，仅当原始值是有限正数时返回 true。
// 接受 float64/int/json.Number；字符串/布尔/null/对象/数组/NaN/Inf/<=0 一律返回 false。
func coercePositiveFloat(raw interface{}) (float64, bool) {
	switch v := raw.(type) {
	case float64:
		return v, true
	case int:
		return float64(v), true
	case int64:
		return float64(v), true
	case json.Number:
		f, err := v.Float64()
		return f, err == nil
	default:
		return 0, false
	}
}

// isFiniteNonZeroPositive 判断是否有限且 > 0。
// plot_scales 必须是有限数（不能是 NaN/Inf）、且 > 0（防止除零）；
// display_args 中未显式写方括号时，解析器默认填 100，仍 > 0，但这里仍做防御性检查。
func isFiniteNonZeroPositive(f float64) bool {
	return !math.IsNaN(f) && !math.IsInf(f, 0) && f > 0
}

// ExportBatch 导出批量仿真结果
func (b *SystemBinding) ExportBatch(configPath string, cycles int, exportPath string) error {
	if err := b.ensureDataFactory(); err != nil {
		return err
	}
	if exportPath == "" {
		return fmt.Errorf("导出路径不能为空")
	}
	if cycles <= 0 {
		return fmt.Errorf("周期数必须大于 0")
	}
	if err := b.beginBatch(); err != nil {
		return err
	}
	defer b.endBatch()

	args := []string{"-c", configPath, "--batch", fmt.Sprintf("%d", cycles), "--export", exportPath}
	cmd := b.dfLaunch.command(b.commandFactory, args...)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("DataFactory 运行失败: %w\n%s", err, string(output))
	}
	return validateBatchCSV(exportPath)
}

// ExportBatchFormatted 重跑批量仿真并按引擎模板导出（时间列 + 表头，csv/xlsx）。
// columns 为空时用 DSL display_args；sheetName 仅对 Excel 生效。
// 注：本方法为旧的重跑导出路径，当前主流程不使用（主流程用 ExportRowsFormatted 导出内存结果）；
// xls 暂未启用（运行环境缺 xlwt）。
func (b *SystemBinding) ExportBatchFormatted(configPath string, cycles int, exportPath string, format string, columns []string, sheetName string) error {
	// 在函数开头统一规范化 format（trim + lowercase），后续 format 门禁与参数构造必须使用同一 fmtLower，
	// 避免把原始的 " xlsx " 等带空格串透传给 Python argparse（choices 为精确匹配，会被拒）。
	fmtLower := strings.ToLower(strings.TrimSpace(format))
	// 格式门禁前置：xls 当前版本暂不支持，未知格式直接拒绝；都不启动子进程。
	switch fmtLower {
	case "csv", "xlsx":
	case "xls":
		return fmt.Errorf("当前版本暂不支持 xls，请使用 xlsx 或 csv")
	default:
		return fmt.Errorf("不支持的导出格式: %s", format)
	}
	if err := b.ensureDataFactory(); err != nil {
		return err
	}
	if exportPath == "" {
		return fmt.Errorf("导出路径不能为空")
	}
	if cycles <= 0 {
		return fmt.Errorf("周期数必须大于 0")
	}
	if err := b.beginBatch(); err != nil {
		return err
	}
	defer b.endBatch()

	args := buildBatchExportArgs(configPath, cycles, exportPath, fmtLower, columns, sheetName)
	cmd := b.dfLaunch.command(b.commandFactory, args...)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("DataFactory 导出失败: %w\n%s", err, string(output))
	}

	info, err := os.Stat(exportPath)
	if err != nil {
		return fmt.Errorf("导出文件未生成: %w", err)
	}
	if info.Size() == 0 {
		return fmt.Errorf("导出文件为空")
	}
	return nil
}

// buildBatchExportArgs 构造模板导出的 CLI 参数（纯函数，便于测试）。
//
// format 调用方已规范化（trim + lowercase）。此处再做一次防御性 trim + lowercase，
// 保证最终参数中 --format 不会带前后空格。
func buildBatchExportArgs(configPath string, cycles int, exportPath string, format string, columns []string, sheetName string) []string {
	fmtLower := strings.ToLower(strings.TrimSpace(format))
	args := []string{
		"-c", configPath,
		"--batch", fmt.Sprintf("%d", cycles),
		"--export", exportPath,
		"--format", fmtLower,
	}
	if len(columns) > 0 {
		args = append(args, "--columns", strings.Join(columns, ","))
	}
	if sheetName != "" {
		args = append(args, "--sheet-name", sheetName)
	}
	return args
}

// ExportRowsFormatted 将冻结的仿真结果按 prediction 模板导出为 csv/xlsx。
// columns 只包含用户选择的业务信号（前端 sanitizeExportColumns 已过滤内部列），
// rows 是当前内存结果快照（包含 _sim_time / _need_sample 等内部元数据）。
// CSV 与 XLSX 均通过 DataFactory Python 转换器（--convert-export）生成，保证：
//   - 两行表头（timeStamp / 时间戳 + 某工业数据）
//   - 时间列使用 datetime.fromtimestamp 格式化为 %Y-%m-%d %H:%M:%S
//   - 仅导出 need_sample=true 的行
//   - 列顺序与采样筛选在两种格式之间一致
//
// xls 当前版本暂不支持（运行环境缺 xlwt），返回明确错误。
// 导出是格式转换任务，不是批量仿真任务：不调用 beginBatch，不增加 activeBatches。
func (b *SystemBinding) ExportRowsFormatted(columns []string, rows []map[string]any, exportPath string, format string, sheetName string) error {
	if strings.TrimSpace(exportPath) == "" {
		return fmt.Errorf("导出路径不能为空")
	}
	if len(columns) == 0 {
		return fmt.Errorf("列为空，无法导出")
	}
	fmtLower := strings.ToLower(strings.TrimSpace(format))
	switch fmtLower {
	case "csv", "xlsx":
	case "xls":
		return fmt.Errorf("当前版本暂不支持 xls，请使用 xlsx 或 csv")
	default:
		return fmt.Errorf("不支持的导出格式: %s", format)
	}

	if err := b.ensureDataFactory(); err != nil {
		return err
	}
	workDir, err := os.MkdirTemp("", "review3-export-*")
	if err != nil {
		return fmt.Errorf("创建导出临时目录失败: %w", err)
	}
	defer os.RemoveAll(workDir)

	rowsJSON := filepath.Join(workDir, "rows.json")
	payload := map[string]any{"columns": columns, "rows": rows}
	data, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("序列化导出行失败: %w", err)
	}
	if err := os.WriteFile(rowsJSON, data, 0o644); err != nil {
		return fmt.Errorf("写入导出临时文件失败: %w", err)
	}

	args := buildConvertExportArgs(rowsJSON, exportPath, fmtLower, sheetName)
	cmd := b.dfLaunch.command(b.commandFactory, args...)
	output, err := cmd.CombinedOutput()
	if err != nil {
		// 失败信息包含实际转换器（DataFactory.exe 路径 或 Python + standalone_main.py），
		// 并识别旧版 DataFactory 不支持 --convert-export 的情况，避免伪装成普通导出失败。
		return fmt.Errorf("DataFactory 导出失败（转换器: %s）: %s", b.dfLaunch.displayPath(), convertExportErrorMessage(err, output))
	}

	info, err := os.Stat(exportPath)
	if err != nil {
		return fmt.Errorf("导出文件未生成（转换器: %s）: %w", b.dfLaunch.displayPath(), err)
	}
	if info.Size() == 0 {
		return fmt.Errorf("导出文件为空（转换器: %s）", b.dfLaunch.displayPath())
	}
	return nil
}

// convertExportErrorMessage 生成导出转换失败信息：
// 识别旧版 DataFactory 不支持 --convert-export 的情况（argparse 报 unrecognized arguments），
// 给出明确升级提示；否则原样返回底层错误与输出，便于定位实际调用的运行时。
func convertExportErrorMessage(err error, output []byte) string {
	text := string(output)
	if strings.Contains(text, "convert-export") && strings.Contains(text, "unrecognized arguments") {
		return "当前 DataFactory 版本不支持内存结果导出，请更新 DataFactory.exe"
	}
	return fmt.Sprintf("%v\n%s", err, text)
}

// defaultExportTemplate 是当前唯一的导出模板（data_factory_server 标准）。
// 不依赖 Python argparse 的隐含默认值，避免未来默认值变化导致格式漂移。
const defaultExportTemplate = "prediction"

// buildConvertExportArgs 构造 --convert-export 的 CLI 参数（纯函数，便于测试）。
// 显式传入 --template prediction + 仅在 xlsx 时传 --sheet-name（CSV 不需要工作表名）。
func buildConvertExportArgs(rowsJSON string, exportPath string, format string, sheetName string) []string {
	args := []string{
		"--convert-export",
		"--rows-json", rowsJSON,
		"--export", exportPath,
		"--format", format,
		"--template", defaultExportTemplate,
	}
	if strings.EqualFold(format, "xlsx") && sheetName != "" {
		args = append(args, "--sheet-name", sheetName)
	}
	return args
}

// validateBatchCSV 确认目标 CSV 存在、非空、且至少有一行数据（不只表头）。
func validateBatchCSV(path string) error {
	info, err := os.Stat(path)
	if err != nil {
		return fmt.Errorf("CSV 不存在: %w", err)
	}
	if info.Size() == 0 {
		return fmt.Errorf("CSV 文件为空")
	}

	file, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("读取 CSV 失败: %w", err)
	}
	defer file.Close()

	reader := csv.NewReader(file)
	if _, err := reader.Read(); err != nil {
		return fmt.Errorf("解析 CSV 表头失败: %w", err)
	}
	if _, err := reader.Read(); err == io.EOF {
		return fmt.Errorf("CSV 无数据行")
	} else if err != nil {
		return fmt.Errorf("解析 CSV 失败: %w", err)
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
			return BatchResult{}, fmt.Errorf("解析 CSV 失败: %w", err)
		}
		row := map[string]any{"_cycle": rowIdx}
		for i, value := range record {
			if i >= len(headers) {
				break
			}
			parsed, err := parseBatchCell(headers[i], value)
			if err != nil {
				return BatchResult{}, fmt.Errorf("第 %d 行字段 %s 解析失败: %w", rowIdx+1, headers[i], err)
			}
			row[headers[i]] = parsed
		}
		rows = append(rows, row)
		rowIdx++
	}

	if len(rows) == 0 {
		return BatchResult{}, fmt.Errorf("CSV 无数据行")
	}

	return BatchResult{
		Columns: append([]string{"_cycle"}, headers...),
		Rows:    rows,
	}, nil
}

// parseBatchCell 按列名决定如何解析 CSV 单元格的字符串值（纯函数，便于测试）。
//   - "_need_sample"：必须解析为 bool；接受 "true"/"false"/"1"/"0"（大小写不敏感）；
//     缺失或非法时返回明确错误，不静默回退 false。
//   - "_sim_time"：必须解析为有限 float64；缺失或非数值返回 "缺少有效 _sim_time" 错误。
//   - 其他业务列：优先 ParseFloat；失败时保留原字符串（不丢失文本信号）。
func parseBatchCell(header string, value string) (any, error) {
	switch header {
	case "_need_sample":
		normalized := strings.ToLower(strings.TrimSpace(value))
		switch normalized {
		case "true", "1":
			return true, nil
		case "false", "0":
			return false, nil
		default:
			return nil, fmt.Errorf("缺少有效 _need_sample")
		}
	case "_sim_time":
		f, err := strconv.ParseFloat(strings.TrimSpace(value), 64)
		if err != nil {
			return nil, fmt.Errorf("缺少有效 _sim_time")
		}
		if math.IsNaN(f) || math.IsInf(f, 0) {
			return nil, fmt.Errorf("缺少有效 _sim_time")
		}
		return f, nil
	default:
		if f, err := strconv.ParseFloat(strings.TrimSpace(value), 64); err == nil {
			return f, nil
		}
		return value, nil
	}
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

// defaultReadinessChecker 默认的 readiness checker。
// 必须使用入参 token（生产环境 Bearer）调用 /api/status，不依赖外部全局 token 与硬编码。
func defaultReadinessChecker(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
	url := fmt.Sprintf("http://%s:%d/api/status", apiHost, apiPort)
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return false, "", err
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
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
