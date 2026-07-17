package engine

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sync"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

// EngineProc 管理 DataFactory 子进程的生命周期。
// workDir 是 review3 目录（含 standalone_main.py 和 config/）。
// python 从 PATH 找（python 或 python3），也允许用户手动指定。
type EngineProc struct {
	ctx     context.Context
	mu      sync.Mutex
	cmd     *exec.Cmd
	running bool
}

func NewEngineProc() *EngineProc {
	return &EngineProc{}
}

func (p *EngineProc) SetContext(ctx context.Context) {
	p.ctx = ctx
}

// IsRunning 返回子进程是否在运行
func (p *EngineProc) IsRunning() bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.running && p.cmd != nil && p.cmd.ProcessState == nil
}

// resolvePython 解析 python 可执行文件路径
// pythonPath 为空时从 PATH 查找 python/python3
func resolvePython(pythonPath string) (string, error) {
	if pythonPath != "" {
		if _, err := os.Stat(pythonPath); err == nil {
			return pythonPath, nil
		}
	}
	// 从 PATH 找
	for _, name := range []string{"python", "python3"} {
		if p, err := exec.LookPath(name); err == nil {
			return p, nil
		}
	}
	return "", fmt.Errorf("未找到 python 可执行文件（PATH 中无 python/python3）")
}

// StartRealtime 启动实时+OPC UA 模式（持续运行）
// workDir: review3 目录（含 standalone_main.py）
// pythonPath: python.exe 路径（空则从 PATH 查找）
func (p *EngineProc) StartRealtime(workDir, pythonPath, yamlPath, mode string, cycleTime float64, port int) (int, error) {
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.running {
		return 0, fmt.Errorf("引擎已在运行中")
	}

	py, err := resolvePython(pythonPath)
	if err != nil {
		return 0, err
	}

	scriptPath := filepath.Join(workDir, "standalone_main.py")
	if _, err := os.Stat(scriptPath); err != nil {
		return 0, fmt.Errorf("找不到 standalone_main.py: %s", scriptPath)
	}

	args := []string{scriptPath, "-c", yamlPath}
	if port > 0 {
		args = append(args, "--port", fmt.Sprintf("%d", port))
	}
	if mode != "" {
		args = append(args, "--mode", mode)
	}
	if cycleTime > 0 {
		args = append(args, "--cycle-time", fmt.Sprintf("%g", cycleTime))
	}

	cmd := exec.Command(py, args...)
	cmd.Dir = workDir

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return 0, err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return 0, err
	}

	if err := cmd.Start(); err != nil {
		return 0, fmt.Errorf("启动引擎失败: %w", err)
	}

	p.cmd = cmd
	p.running = true
	pid := cmd.Process.Pid

	go forwardLog(p.ctx, stdout)
	go forwardLog(p.ctx, stderr)

	go func() {
		cmd.Wait()
		p.mu.Lock()
		p.running = false
		p.cmd = nil
		p.mu.Unlock()
		if p.ctx != nil {
			runtime.EventsEmit(p.ctx, "engine:stopped", nil)
		}
	}()

	return pid, nil
}

// StartBatch 启动批量仿真模式（跑完即退出）
func (p *EngineProc) StartBatch(workDir, pythonPath, yamlPath string, cycles int, cycleTime float64, exportPath string) error {
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.running {
		return fmt.Errorf("引擎已在运行中")
	}

	py, err := resolvePython(pythonPath)
	if err != nil {
		return err
	}

	scriptPath := filepath.Join(workDir, "standalone_main.py")
	if _, err := os.Stat(scriptPath); err != nil {
		return fmt.Errorf("找不到 standalone_main.py: %s", scriptPath)
	}

	args := []string{scriptPath, "-c", yamlPath,
		"--batch", fmt.Sprintf("%d", cycles),
		"--export", exportPath}
	if cycleTime > 0 {
		args = append(args, "--cycle-time", fmt.Sprintf("%g", cycleTime))
	}

	cmd := exec.Command(py, args...)
	cmd.Dir = workDir

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return err
	}

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("启动批量仿真失败: %w", err)
	}

	p.cmd = cmd
	p.running = true

	go forwardLog(p.ctx, stdout)
	go forwardLog(p.ctx, stderr)

	go func() {
		cmd.Wait()
		p.mu.Lock()
		p.running = false
		p.cmd = nil
		p.mu.Unlock()
		if p.ctx != nil {
			runtime.EventsEmit(p.ctx, "batch:finished", exportPath)
		}
	}()

	return nil
}

// Stop 停止子进程
func (p *EngineProc) Stop() error {
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.cmd == nil || p.cmd.Process == nil {
		return fmt.Errorf("引擎未在运行")
	}
	return p.cmd.Process.Kill()
}

// forwardLog 把子进程 stdout/stderr 转发为 Wails 事件
func forwardLog(ctx context.Context, pipe io.Reader) {
	scanner := bufio.NewScanner(pipe)
	for scanner.Scan() {
		if ctx != nil {
			runtime.EventsEmit(ctx, "engine:log", scanner.Text())
		}
	}
}
