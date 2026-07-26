package bindings

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"time"
)

// DataFactoryServiceManager 负责启动、监控和关闭常驻 DataFactoryService 进程（todo.md §5.1）。
//
// 职责：
//   - 解析 <exe>/DataFactoryService.exe 路径（生产）或 python standalone_main.py --service（开发）
//   - 启动子进程（Windows 上无控制台窗口，todo.md §5.5）
//   - 选择 127.0.0.1 随机可用端口（todo.md §5.2 / §5.4）
//   - 生成随机 API Token（todo.md §5.2）
//   - 等待 /api/health 就绪（JSON 解析，todo.md §5.3）
//   - 暴露统一 DataFactoryServiceClient（todo.md §5.2）
//   - 监控进程异常退出（todo.md §5.6）
//   - 应用退出时优雅关闭，超时强制 kill（todo.md §6）
type DataFactoryServiceManager struct {
	mu sync.Mutex

	host  string // 始终 127.0.0.1（todo.md §5.2）
	port  int
	token string
	pid   int

	cmd       *exec.Cmd
	state     string // starting / ready / stopping / stopped / failed
	stateTime time.Time
	exitCode  int
	exitErr   error

	// logs 缓存最近 N 行 stderr/stdout，便于错误展示
	stderrBuf *lineBuffer
	stdoutBuf *lineBuffer

	// client 统一服务客户端（todo.md §5.2）
	client *DataFactoryServiceClient

	// shutdown 等待
	shutdownCtx    context.Context
	shutdownCancel context.CancelFunc

	// exitCh 进程退出通知
	exitCh chan struct{}

	// onExit 异常退出回调（todo.md §5.6）
	onExit func(exitCode int, err error)
}

// 服务启动相关常量
const (
	serviceStartTimeout    = 15 * time.Second
	serviceStopTimeout     = 5 * time.Second
	serviceHealthInterval  = 200 * time.Millisecond
	serviceMaxPortRetries  = 5 // todo.md §5.4
)

// NewDataFactoryServiceManager 创建并启动常驻服务。
//
// devMode = true：使用 python standalone_main.py --service（开发环境）
// devMode = false：使用 <exe>/DataFactoryService.exe（生产）
func NewDataFactoryServiceManager(devMode bool) (*DataFactoryServiceManager, error) {
	exeDir, err := ResolveExeDir()
	if err != nil {
		return nil, fmt.Errorf("解析 EXE 目录失败: %w", err)
	}

	m := &DataFactoryServiceManager{
		host:      "127.0.0.1",
		state:     "starting",
		stateTime: time.Now(),
		stderrBuf: newLineBuffer(50),
		stdoutBuf: newLineBuffer(50),
		exitCh:    make(chan struct{}),
	}
	m.shutdownCtx, m.shutdownCancel = context.WithCancel(context.Background())

	// 解析 service EXE / python
	var serviceExe string
	var baseArgs []string
	if devMode {
		repoRoot, err := resolveRepoRootForDevService(exeDir)
		if err != nil {
			// wails generate module 等场景：找不到 standalone_main.py 时跳过启动
			// 返回 nil 和 error，让调用方决定是否继续（生产模式必须报错）
			return nil, fmt.Errorf("开发模式：找不到 review3 仓库根: %w", err)
		}
		serviceExe = "python"
		baseArgs = []string{filepath.Join(repoRoot, "standalone_main.py"), "--service"}
	} else {
		exePath := filepath.Join(exeDir, "DataFactoryService.exe")
		if _, err := os.Stat(exePath); err != nil {
			return nil, fmt.Errorf("未找到 DataFactoryService.exe: %s", exePath)
		}
		serviceExe = exePath
		baseArgs = []string{"--service"}
	}

	// 端口重试（todo.md §5.4）
	var lastErr error
	for attempt := 0; attempt < serviceMaxPortRetries; attempt++ {
		port, err := pickFreePort("127.0.0.1")
		if err != nil {
			lastErr = fmt.Errorf("选择服务端口失败: %w", err)
			continue
		}
		m.port = port

		// 每次重试生成新 Token（todo.md §5.4）
		tokenBytes := make([]byte, 24)
		if _, err := rand.Read(tokenBytes); err != nil {
			lastErr = fmt.Errorf("生成 API Token 失败: %w", err)
			continue
		}
		m.token = hex.EncodeToString(tokenBytes)

		// 构造完整参数
		args := append(baseArgs,
			"--api-host", "127.0.0.1",
			"--api-port", fmt.Sprintf("%d", port),
			"--api-token", m.token,
		)

		cmd := exec.Command(serviceExe, args...)
		configureBackgroundProcess(cmd) // todo.md §5.5
		// todo.md §13.2：前端不持有 Token，由 Go 代理。设置 DATAFACTORY_NO_AUTH=1 让 Python 服务跳过前端鉴权。
		cmd.Env = append(os.Environ(), "DATAFACTORY_NO_AUTH=1")

		stdout, err := cmd.StdoutPipe()
		if err != nil {
			lastErr = fmt.Errorf("创建 stdout 管道失败: %w", err)
			continue
		}
		stderr, err := cmd.StderrPipe()
		if err != nil {
			lastErr = fmt.Errorf("创建 stderr 管道失败: %w", err)
			continue
		}

		if err := cmd.Start(); err != nil {
			lastErr = fmt.Errorf("启动 DataFactoryService 失败: %w", err)
			continue
		}
		m.cmd = cmd
		m.pid = cmd.Process.Pid

		go m.pumpOutput(stdout, m.stdoutBuf)
		go m.pumpOutput(stderr, m.stderrBuf)
		go m.monitorExit()

		// 等待 /api/health 就绪（JSON 解析，todo.md §5.3）
		m.client = NewDataFactoryServiceClient(m.host, m.port, m.token)
		if err := m.waitForHealth(serviceStartTimeout); err != nil {
			// 启动失败回收进程
			_ = m.killProcess()
			<-m.exitCh
			lastErr = fmt.Errorf("等待服务 health 超时: %w\n最近日志:\n%s", err, m.RecentLogs())
			continue
		}

		m.setState("ready")
		return m, nil
	}

	return nil, fmt.Errorf("服务启动失败（已重试 %d 次）: %w", serviceMaxPortRetries, lastErr)
}

// monitorExit 监控进程退出（todo.md §5.6）。
func (m *DataFactoryServiceManager) monitorExit() {
	err := m.cmd.Wait()
	m.mu.Lock()
	m.exitErr = err
	if m.cmd.ProcessState != nil {
		m.exitCode = m.cmd.ProcessState.ExitCode()
	}
	// 正常关闭（stopping/stopped）不记录为异常
	if m.state != "stopping" && m.state != "stopped" {
		m.state = "failed"
		m.stateTime = time.Now()
	}
	close(m.exitCh)
	m.mu.Unlock()

	// 通知回调
	if m.onExit != nil && m.state == "failed" {
		m.onExit(m.exitCode, err)
	}
}

// Host 返回服务监听地址（127.0.0.1）。
func (m *DataFactoryServiceManager) Host() string { return m.host }

// Port 返回实际使用的服务端口（todo.md §5.2）。
func (m *DataFactoryServiceManager) Port() int { return m.port }

// Token 返回 API Token（todo.md §5.2：仅 Go 内部使用，不暴露给前端）。
func (m *DataFactoryServiceManager) Token() string { return m.token }

// PID 返回服务进程 PID（todo.md §5.1）。
func (m *DataFactoryServiceManager) PID() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.pid
}

// Client 返回统一服务客户端（todo.md §5.2）。
func (m *DataFactoryServiceManager) Client() *DataFactoryServiceClient {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.client
}

// State 返回当前服务状态。
func (m *DataFactoryServiceManager) State() string {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.state
}

// RecentLogs 返回服务最近输出（用于错误诊断）。
func (m *DataFactoryServiceManager) RecentLogs() string {
	out := m.stdoutBuf.String()
	if s := m.stderrBuf.String(); s != "" {
		if out != "" {
			out += "\n"
		}
		out += s
	}
	return out
}

// SetOnExit 设置异常退出回调（todo.md §5.6）。
func (m *DataFactoryServiceManager) SetOnExit(fn func(exitCode int, err error)) {
	m.mu.Lock()
	m.onExit = fn
	m.mu.Unlock()
}

func (m *DataFactoryServiceManager) setState(s string) {
	m.mu.Lock()
	m.state = s
	m.stateTime = time.Now()
	m.mu.Unlock()
}

// waitForHealth 轮询 /api/health 直到返回 ok=true 或超时（todo.md §5.3）。
func (m *DataFactoryServiceManager) waitForHealth(timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for {
		if time.Now().After(deadline) {
			return fmt.Errorf("超过 %s 仍未就绪", timeout)
		}
		// 检查进程是否已退出
		select {
		case <-m.exitCh:
			return fmt.Errorf("服务进程已退出 exit code %d", m.exitCode)
		default:
		}
		// JSON 解析 health（todo.md §5.3）
		if _, err := m.client.CheckHealth(m.shutdownCtx); err == nil {
			return nil
		}
		time.Sleep(serviceHealthInterval)
	}
}

// Stop 优雅停止服务（todo.md §6）。
//
// 流程：
//  1. POST /api/service/shutdown（发送合法 JSON body，todo.md §6.1）
//  2. 检查响应（todo.md §6.2）
//  3. 等 process 退出（最多 serviceStopTimeout）
//  4. 超时后 kill
func (m *DataFactoryServiceManager) Stop() error {
	if m == nil || m.cmd == nil || m.cmd.Process == nil {
		return nil
	}
	m.setState("stopping")

	// 发送合法 JSON body（todo.md §6.1）
	shutdownReq := map[string]string{"reason": "config-tool-exit"}
	var shutdownResp struct {
		OK           bool   `json:"ok"`
		ServiceState string `json:"serviceState"`
		RuntimeState string `json:"runtimeState"`
	}
	err := m.client.DoJSON(context.Background(), "POST", "/api/service/shutdown", shutdownReq, &shutdownResp)
	if err != nil {
		// 请求失败后进入超时强杀流程（todo.md §6.2）
		_ = m.killProcess()
		<-m.exitCh
		m.setState("stopped")
		return nil
	}
	if !shutdownResp.OK {
		_ = m.killProcess()
		<-m.exitCh
		m.setState("stopped")
		return nil
	}

	// 等待 process 退出
	select {
	case <-m.exitCh:
		m.setState("stopped")
		return nil
	case <-time.After(serviceStopTimeout):
		// 超时强制 kill（todo.md §6.2）
		_ = m.killProcess()
		<-m.exitCh
		m.setState("stopped")
		return nil
	}
}

func (m *DataFactoryServiceManager) killProcess() error {
	if m == nil || m.cmd == nil || m.cmd.Process == nil {
		return nil
	}
	return m.cmd.Process.Kill()
}

func (m *DataFactoryServiceManager) pumpOutput(r io.Reader, buf *lineBuffer) {
	scanner := newLineScanner(r)
	for scanner.Scan() {
		buf.Append(scanner.Text())
	}
}

// pickFreePort 让 OS 在 127.0.0.1 上挑一个可用端口（todo.md §5.2）。
func pickFreePort(host string) (int, error) {
	l, err := net.Listen("tcp", host+":0")
	if err != nil {
		return 0, err
	}
	addr := l.Addr().(*net.TCPAddr)
	port := addr.Port
	l.Close()
	return port, nil
}

// resolveRepoRootForDevService 在 devMode 下从 exeDir 向上找到 review3 仓库根（含 standalone_main.py）。
func resolveRepoRootForDevService(exeDir string) (string, error) {
	dir := exeDir
	for i := 0; i < 8; i++ {
		candidate := filepath.Join(dir, "standalone_main.py")
		if _, err := os.Stat(candidate); err == nil {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return "", errors.New("未找到 standalone_main.py")
}

// lineBuffer 是线程安全的环形行缓冲（保留最近 N 行）。
type lineBuffer struct {
	mu   sync.Mutex
	cap  int
	ring []string
	idx  int
	full bool
}

func newLineBuffer(cap int) *lineBuffer {
	return &lineBuffer{cap: cap, ring: make([]string, cap)}
}

func (b *lineBuffer) Append(line string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.ring[b.idx] = line
	b.idx = (b.idx + 1) % b.cap
	if b.idx == 0 {
		b.full = true
	}
}

func (b *lineBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	if !b.full {
		return joinLines(b.ring[:b.idx])
	}
	out := make([]string, 0, b.cap)
	start := b.idx
	for i := 0; i < b.cap; i++ {
		out = append(out, b.ring[(start+i)%b.cap])
	}
	return joinLines(out)
}

func joinLines(parts []string) string {
	out := ""
	for i, p := range parts {
		if i > 0 {
			out += "\n"
		}
		out += p
	}
	return out
}

// lineScanner 是 bufio.Scanner 的最小子集。
type lineScanner struct {
	r   io.Reader
	buf []byte
}

func newLineScanner(r io.Reader) *lineScanner { return &lineScanner{r: r} }

func (s *lineScanner) Scan() bool {
	for {
		b, err := s.readByte()
		if err != nil {
			if len(s.buf) > 0 {
				return true
			}
			return false
		}
		if b == '\n' {
			return true
		}
		s.buf = append(s.buf, b)
	}
}

func (s *lineScanner) Text() string {
	out := string(s.buf)
	s.buf = s.buf[:0]
	return out
}

func (s *lineScanner) readByte() (byte, error) {
	var b [1]byte
	n, err := s.r.Read(b[:])
	if n > 0 {
		return b[0], nil
	}
	return 0, err
}
