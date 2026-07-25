package bindings

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sync"
	"syscall"
	"time"
)

// DataFactoryServiceManager 负责启动、监控和关闭常驻 DataFactoryService 进程（todo.md §7.1）。
//
// 职责：
//   - 解析 <exe>/DataFactoryService.exe 路径（生产）或 python standalone_main.py --service（开发）
//   - 启动子进程（Windows 上无控制台窗口）
//   - 选择 127.0.0.1 随机可用端口（todo.md §7.2）
//   - 生成随机 API Token（todo.md §7.3）
//   - 等待 /api/health 就绪
//   - 暴露统一 HTTP Client（统一加 Authorization Bearer header）
//   - 应用退出时优雅关闭，超时强制 kill
type DataFactoryServiceManager struct {
	mu sync.Mutex

	host  string // 始终 127.0.0.1（todo.md §7.2）
	port  int
	token string

	cmd       *exec.Cmd
	state     string // starting / ready / stopping / failed
	stateTime time.Time

	// logs 缓存最近 N 行 stderr/stdout，便于错误展示
	stderrBuf *lineBuffer
	stdoutBuf *lineBuffer

	// httpClient 注入 Bearer token
	httpClient *http.Client

	// shutdown 等待
	shutdownCtx    context.Context
	shutdownCancel context.CancelFunc
}

// serviceStartTimeout 是等待 /api/health 就绪的超时。
const serviceStartTimeout = 15 * time.Second

// serviceStopTimeout 是优雅停止服务的超时。
const serviceStopTimeout = 5 * time.Second

// serviceHealthInterval 是轮询 /api/health 的间隔。
const serviceHealthInterval = 200 * time.Millisecond

// NewDataFactoryServiceManager 创建并启动常驻服务。
//
// devMode = true：使用 python standalone_main.py --service（开发环境）
// devMode = false：使用 <exe>/DataFactoryService.exe（生产）
func NewDataFactoryServiceManager(devMode bool) (*DataFactoryServiceManager, error) {
	exeDir, err := ResolveExeDir()
	if err != nil {
		return nil, fmt.Errorf("解析 EXE 目录失败: %w", err)
	}
	// 随机 127.0.0.1 端口
	port, err := pickFreePort("127.0.0.1")
	if err != nil {
		return nil, fmt.Errorf("选择服务端口失败: %w", err)
	}
	// 随机 Token
	tokenBytes := make([]byte, 24)
	if _, err := rand.Read(tokenBytes); err != nil {
		return nil, fmt.Errorf("生成 API Token 失败: %w", err)
	}
	token := hex.EncodeToString(tokenBytes)

	m := &DataFactoryServiceManager{
		host:     "127.0.0.1",
		port:     port,
		token:    token,
		state:    "starting",
		stateTime: time.Now(),
		stderrBuf: newLineBuffer(50),
		stdoutBuf: newLineBuffer(50),
		httpClient: &http.Client{Timeout: 10 * time.Second},
	}
	m.shutdownCtx, m.shutdownCancel = context.WithCancel(context.Background())

	// 解析 service EXE / python
	var serviceExe string
	var serviceArgs []string
	if devMode {
		// 开发模式：使用源码 python standalone_main.py --service
		// 假设 review3/ 与 config-tool/ 同级
		repoRoot, err := resolveRepoRootForDevService(exeDir)
		if err != nil {
			return nil, fmt.Errorf("开发模式：找不到 review3 仓库根: %w", err)
		}
		serviceExe = "python"
		serviceArgs = []string{
			filepath.Join(repoRoot, "standalone_main.py"),
			"--service",
			"--api-host", "127.0.0.1",
			"--api-port", fmt.Sprintf("%d", port),
			"--api-token", token,
		}
	} else {
		// 生产模式：<exe>/DataFactoryService.exe
		exePath := filepath.Join(exeDir, "DataFactoryService.exe")
		if _, err := os.Stat(exePath); err != nil {
			return nil, fmt.Errorf("未找到 DataFactoryService.exe: %s", exePath)
		}
		serviceExe = exePath
		serviceArgs = []string{
			"--service",
			"--api-host", "127.0.0.1",
			"--api-port", fmt.Sprintf("%d", port),
			"--api-token", token,
		}
	}

	cmd := exec.Command(serviceExe, serviceArgs...)
	hideWindow(cmd)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, fmt.Errorf("创建 stdout 管道失败: %w", err)
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return nil, fmt.Errorf("创建 stderr 管道失败: %w", err)
	}

	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("启动 DataFactoryService 失败: %w", err)
	}
	m.cmd = cmd

	go m.pumpOutput(stdout, m.stdoutBuf)
	go m.pumpOutput(stderr, m.stderrBuf)

	// 等待 /api/health 就绪
	if err := m.waitForHealth(serviceStartTimeout); err != nil {
		// 启动失败也要回收进程
		_ = m.killProcess()
		return nil, fmt.Errorf("等待服务 health 超时: %w\n最近日志:\n%s", err, m.RecentLogs())
	}

	m.setState("ready")
	return m, nil
}

// Host 返回服务监听地址（127.0.0.1）。
func (m *DataFactoryServiceManager) Host() string { return m.host }

// Port 返回实际使用的服务端口（todo.md §7.2）。
func (m *DataFactoryServiceManager) Port() int { return m.port }

// Token 返回 API Token（todo.md §7.3：仅 Go 内部使用，不暴露给前端）。
func (m *DataFactoryServiceManager) Token() string { return m.token }

// HTTPClient 返回带 Bearer Token 的 HTTP 客户端。
func (m *DataFactoryServiceManager) HTTPClient() *http.Client { return m.httpClient }

// RecentLogs 返回服务最近输出（用于错误诊断）。
func (m *DataFactoryServiceManager) RecentLogs() string {
	out := m.stdoutBuf.String() + "\n" + m.stderrBuf.String()
	return out
}

// State 返回当前服务状态。
func (m *DataFactoryServiceManager) State() string {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.state
}

func (m *DataFactoryServiceManager) setState(s string) {
	m.mu.Lock()
	m.state = s
	m.stateTime = time.Now()
	m.mu.Unlock()
}

// waitForHealth 轮询 /api/health 直到返回 ok=true 或超时。
func (m *DataFactoryServiceManager) waitForHealth(timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	url := fmt.Sprintf("http://%s:%d/api/health", m.host, m.port)
	for {
		if time.Now().After(deadline) {
			return fmt.Errorf("超过 %s 仍未就绪", timeout)
		}
		req, _ := http.NewRequestWithContext(m.shutdownCtx, "GET", url, nil)
		req.Header.Set("Authorization", "Bearer "+m.token)
		resp, err := m.httpClient.Do(req)
		if err == nil {
			body, _ := io.ReadAll(resp.Body)
			resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				// 简单校验
				if containsOK(body) {
					return nil
				}
			}
		}
		// 检查进程是否已退出
		if m.cmd != nil && m.cmd.ProcessState != nil && m.cmd.ProcessState.Exited() {
			return fmt.Errorf("服务进程已退出 exit code %d", m.cmd.ProcessState.ExitCode())
		}
		time.Sleep(serviceHealthInterval)
	}
}

// Stop 优雅停止服务（todo.md §7.5）。
//
// 流程：
//   1. POST /api/service/shutdown（让服务自行释放）
//   2. 等 process 退出（最多 serviceStopTimeout）
//   3. 超时后 kill
func (m *DataFactoryServiceManager) Stop() error {
	if m == nil || m.cmd == nil || m.cmd.Process == nil {
		return nil
	}
	m.setState("stopping")
	// 尝试优雅关闭
	shutdownURL := fmt.Sprintf("http://%s:%d/api/service/shutdown", m.host, m.port)
	req, _ := http.NewRequest("POST", shutdownURL, nil)
	req.Header.Set("Authorization", "Bearer "+m.token)
	resp, err := m.httpClient.Do(req)
	if err == nil {
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
	}
	// 等待 process 退出
	done := make(chan struct{})
	go func() {
		_ = m.cmd.Wait()
		close(done)
	}()
	select {
	case <-done:
		m.setState("stopped")
		return nil
	case <-time.After(serviceStopTimeout):
		// 超时强制 kill
		_ = m.killProcess()
		<-done
		m.setState("stopped")
		return nil
	}
}

func (m *DataFactoryServiceManager) killProcess() error {
	if m == nil || m.cmd == nil || m.cmd.Process == nil {
		return nil
	}
	// Windows: Kill 强制结束；Unix: SIGKILL
	if runtime.GOOS == "windows" {
		return m.cmd.Process.Kill()
	}
	return m.cmd.Process.Signal(syscall.SIGKILL)
}

func (m *DataFactoryServiceManager) pumpOutput(r io.Reader, buf *lineBuffer) {
	scanner := newLineScanner(r)
	for scanner.Scan() {
		buf.Append(scanner.Text())
	}
}

// hideWindow 在 Windows 上设置 CREATE_NO_WINDOW，避免服务进程弹出命令行窗口（todo.md §7.4）。
// 非 Windows 平台为 no-op。
func hideWindow(cmd *exec.Cmd) {
	if runtime.GOOS != "windows" {
		return
	}
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: 0x08000000, // CREATE_NO_WINDOW
	}
}

// pickFreePort 让 OS 在 127.0.0.1 上挑一个可用端口（todo.md §7.2）。
// 端口冲突时允许重试 5 次。
func pickFreePort(host string) (int, error) {
	const maxAttempts = 5
	for i := 0; i < maxAttempts; i++ {
		l, err := net.Listen("tcp", host+":0")
		if err != nil {
			return 0, err
		}
		addr := l.Addr().(*net.TCPAddr)
		port := addr.Port
		l.Close()
		return port, nil
	}
	return 0, errors.New("无法选择可用端口")
}

// resolveRepoRootForDevService 在 devMode 下从 exeDir 向上找到 review3 仓库根（含 standalone_main.py）。
func resolveRepoRootForDevService(exeDir string) (string, error) {
	// 常见布局：
	//   G:/github/supcon_tools/review3/config-tool/build/bin/config-tool.exe
	//   G:/github/supcon_tools/review3/standalone_main.py
	// 所以 review3/ 在 exeDir 向上 3 层。
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

// lineScanner 是 bufio.Scanner 的最小子集（避免在文件里 import bufio 后被 engine_api 占用）。
type lineScanner struct {
	r io.Reader
	buf []byte
}

func newLineScanner(r io.Reader) *lineScanner { return &lineScanner{r: r} }

func (s *lineScanner) Scan() bool {
	// 简化实现：按 '\n' 切分
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

// containsOK 检查响应 body 中是否包含 ok:true（避免引入 encoding/json）。
func containsOK(body []byte) bool {
	s := string(body)
	return contains(s, "\"ok\":true") || contains(s, "\"ok\": true")
}

func contains(s, substr string) bool {
	for i := 0; i+len(substr) <= len(s); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}