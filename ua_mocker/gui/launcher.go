// -*- coding: utf-8 -*-
/*
launcher.go — 服务进程管控：定位服务程序、生成组态、启动、解析启动标记、停止。

对外接口：
  - ServerProcess：已启动的服务进程（Endpoint/NodeCount/PID/Alive/Stop）
  - LaunchServer(port, cycleMs int) (*ServerProcess, error)
  - LocateServer() (ServerProgram, error)（供诊断用）

集成契约（现有 server_main.py 控制台输出，其 docstring 已钉死格式）：
  - 以「服务启动成功」开头的行 → 行内其余部分为 endpoint
  - 以「节点数量: 」开头的行 → 行内数字为节点数
两标记齐备即视为启动成功；进程在标记齐备前退出即失败，
回读 stderr 末行 / 服务当日日志尾部作为错误详情。
*/
package main

import (
	"bufio"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	markerServerStart = "服务启动成功"        // 启动成功标记（行前缀）
	markerNodeCount   = "节点数量: "          // 节点数标记（行前缀）
	startTimeout      = 20 * time.Second // 启动总超时：26 节点秒级可建，留足慢机器余量
	logFilePrefix     = "ua_mocker"      // 服务日志前缀（log_util.py：ua_mocker_YYYYMMDD.log）
	logDateFormat     = "20060102"       // Go 时间格式模板 = YYYYMMDD
	configFileName    = "ua_types_gui.yaml" // GUI 生成的组态文件名（置于程序目录）
	serverExeName     = "ua_mocker.exe"  // 分发包中的服务程序名（现有 PyInstaller 产物）
	serverScriptName  = "main.py"        // 开发/半分发形态的服务脚本名
	tailLines         = 5                // 错误详情回读的行数
)

// ServerProgram 定位到的服务程序：启动命令 + 参数前缀 + 程序所在目录（用于找日志）
type ServerProgram struct {
	Cmd  string
	Args []string
	Dir  string
}

// startResult 启动标记解析结果
type startResult struct {
	endpoint string
	nodes    int
}

// ServerProcess 一个已启动的服务进程
type ServerProcess struct {
	cmd       *exec.Cmd
	pid       int
	endpoint  string
	nodeCount int
	mu        sync.Mutex
	exited    bool
}

// Endpoint 返回服务启动时上报的 endpoint
func (p *ServerProcess) Endpoint() string { return p.endpoint }

// NodeCount 返回服务启动时上报的节点数
func (p *ServerProcess) NodeCount() int { return p.nodeCount }

// PID 返回服务进程号
func (p *ServerProcess) PID() int { return p.pid }

// Alive 进程是否仍在运行
func (p *ServerProcess) Alive() bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	return !p.exited
}

// markExited 由 Wait 监视 goroutine 调用
func (p *ServerProcess) markExited() {
	p.mu.Lock()
	p.exited = true
	p.mu.Unlock()
}

// Stop 强杀进程树。服务无持久化状态，强杀安全（见设计文档 §6）。
// Windows 用 taskkill /T 杀整棵树（python 可能派生子进程）；其他平台直接 Kill。
func (p *ServerProcess) Stop() error {
	if !p.Alive() {
		return nil
	}
	var err error
	if runtime.GOOS == "windows" {
		err = exec.Command("taskkill", "/T", "/F", "/PID", strconv.Itoa(p.pid)).Run()
	} else if p.cmd.Process != nil {
		err = p.cmd.Process.Kill()
	}
	if err != nil {
		return fmt.Errorf("停止服务失败: %w", err)
	}
	// 等 Wait 监视 goroutine 落地退出状态，最多 3s
	deadline := time.Now().Add(3 * time.Second)
	for p.Alive() && time.Now().Before(deadline) {
		time.Sleep(50 * time.Millisecond)
	}
	return nil
}

// executableDir 当前程序所在目录（wails dev 时为 build/bin，分发时为 exe 目录）
func executableDir() (string, error) {
	exe, err := os.Executable()
	if err != nil {
		return "", fmt.Errorf("无法获取程序路径: %w", err)
	}
	return filepath.Dir(exe), nil
}

func fileExists(p string) bool {
	info, err := os.Stat(p)
	return err == nil && !info.IsDir()
}

// LocateServer 按优先级定位服务程序（见设计文档 §3）：
//  1. GUI exe 同目录的 ua_mocker.exe（分发形态）
//  2. GUI exe 同目录的 main.py + 系统 python
//  3. <exe 目录>/../../../main.py + 系统 python（开发形态：gui/build/bin → 仓库根）
func LocateServer() (ServerProgram, error) {
	exeDir, err := executableDir()
	if err != nil {
		return ServerProgram{}, err
	}
	serverExe := filepath.Join(exeDir, serverExeName)
	if fileExists(serverExe) {
		return ServerProgram{Cmd: serverExe, Dir: exeDir}, nil
	}
	// python 参数带 -u：stdout 重定向到管道时默认块缓冲，启动标记会滞留缓冲区
	// 直到进程退出，导致 GUI 永远等不到「服务启动成功」
	python, pyErr := exec.LookPath("python")
	localScript := filepath.Join(exeDir, serverScriptName)
	if pyErr == nil && fileExists(localScript) {
		return ServerProgram{Cmd: python, Args: []string{"-u", localScript}, Dir: exeDir}, nil
	}
	devScript := filepath.Join(exeDir, "..", "..", "..", serverScriptName)
	if pyErr == nil && fileExists(devScript) {
		abs, err := filepath.Abs(devScript)
		if err != nil {
			return ServerProgram{}, err
		}
		return ServerProgram{Cmd: python, Args: []string{"-u", abs}, Dir: filepath.Dir(abs)}, nil
	}
	msg := "未找到服务程序：请将 " + serverExeName + " 放到本程序同目录"
	if pyErr != nil {
		msg += "（或安装 Python 并提供 " + serverScriptName + "）"
	}
	return ServerProgram{}, errors.New(msg)
}

// processLine 解析一行服务控制台输出。两标记齐备时返回 true。
// 抽为纯函数便于单测（LaunchServer 内部复用）。
func processLine(line string, endpoint *string, nodes *int) bool {
	if strings.HasPrefix(line, markerServerStart) {
		*endpoint = strings.TrimSpace(strings.TrimPrefix(line, markerServerStart))
	} else if strings.HasPrefix(line, markerNodeCount) {
		if n, err := strconv.Atoi(strings.TrimSpace(strings.TrimPrefix(line, markerNodeCount))); err == nil {
			*nodes = n
		}
	}
	return *endpoint != "" && *nodes > 0
}

// tailBuffer 保留最后 n 行的环形缓冲（并发安全），用于错误详情
type tailBuffer struct {
	mu    sync.Mutex
	n     int
	lines []string
}

func (t *tailBuffer) add(s string) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.lines = append(t.lines, s)
	if len(t.lines) > t.n {
		t.lines = t.lines[len(t.lines)-t.n:]
	}
}

func (t *tailBuffer) String() string {
	t.mu.Lock()
	defer t.mu.Unlock()
	return strings.Join(t.lines, "\n")
}

// readLogTail 回读服务当日日志的尾部（log_util.py 把日志写在服务程序所在目录）。
// stderr 无输出时（如错误只进了 logging）作为错误详情的兜底来源。
func readLogTail(dir string) string {
	name := fmt.Sprintf("%s_%s.log", logFilePrefix, time.Now().Format(logDateFormat))
	data, err := os.ReadFile(filepath.Join(dir, name))
	if err != nil {
		return ""
	}
	lines := strings.Split(strings.TrimSpace(string(data)), "\n")
	if len(lines) > tailLines {
		lines = lines[len(lines)-tailLines:]
	}
	return strings.Join(lines, "\n")
}

// LaunchServer 生成组态 → 启动服务 → 等待启动标记，返回受管的 ServerProcess。
// 失败时返回含 stderr/日志尾部详情的错误。
func LaunchServer(port, cycleMs int) (*ServerProcess, error) {
	prog, err := LocateServer()
	if err != nil {
		return nil, err
	}
	exeDir, err := executableDir()
	if err != nil {
		return nil, err
	}
	yamlPath := filepath.Join(exeDir, configFileName)
	if err := os.WriteFile(yamlPath, []byte(GenerateYAML(port, cycleMs)), 0o644); err != nil {
		return nil, fmt.Errorf("写入组态失败: %w", err)
	}

	cmd := exec.Command(prog.Cmd, append(prog.Args, yamlPath)...)
	// 强制 UTF-8 输出：Windows 控制台重定向默认 GBK，会与中文标记串失配
	// PYTHONUNBUFFERED=1：对 PyInstaller exe 形态同样强制行级无缓冲（exe 无法注入 -u 参数）
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8", "PYTHONUNBUFFERED=1")
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return nil, err
	}
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("启动服务程序失败: %w", err)
	}
	p := &ServerProcess{cmd: cmd, pid: cmd.Process.Pid}

	// stderr 末行缓冲（错误详情来源之一）
	stderrTail := &tailBuffer{n: tailLines}
	go func() {
		sc := bufio.NewScanner(stderr)
		for sc.Scan() {
			stderrTail.add(sc.Text())
		}
	}()

	// stdout 标记扫描：齐备即 break；流结束（进程退出）则投递当前（可能不完整）结果
	markerCh := make(chan startResult, 1)
	go func() {
		var res startResult
		sc := bufio.NewScanner(stdout)
		for sc.Scan() {
			if processLine(sc.Text(), &res.endpoint, &res.nodes) {
				break
			}
		}
		markerCh <- res
	}()

	// 进程退出监视
	waitCh := make(chan error, 1)
	go func() { waitCh <- cmd.Wait() }()

	// fail 组装失败错误：reason + stderr 末行 / 日志尾部
	fail := func(reason string) (*ServerProcess, error) {
		time.Sleep(150 * time.Millisecond) // 等 stderr goroutine 收尾
		detail := stderrTail.String()
		if detail == "" {
			detail = readLogTail(prog.Dir)
		}
		if detail == "" {
			detail = "无错误输出"
		}
		return nil, fmt.Errorf("%s：%s", reason, detail)
	}

	select {
	case r := <-markerCh:
		if r.endpoint != "" && r.nodes > 0 {
			p.endpoint, p.nodeCount = r.endpoint, r.nodes
			// 启动成功：后台跟踪退出状态（服务崩溃时前端轮询可感知）
			go func() {
				<-waitCh
				p.markExited()
			}()
			return p, nil
		}
		// stdout 结束但标记不全：等进程退出后取错误详情
		<-waitCh
		p.markExited()
		return fail("服务启动失败（未见完整启动标记）")
	case <-waitCh:
		p.markExited()
		// 进程先退出：给标记解析 500ms 窗口（标记可能已输出但尚未扫完）
		select {
		case r := <-markerCh:
			if r.endpoint != "" && r.nodes > 0 {
				return fail("服务启动后意外退出")
			}
		case <-time.After(500 * time.Millisecond):
		}
		return fail("服务启动失败（进程提前退出）")
	case <-time.After(startTimeout):
		// 超时：杀掉半启动的进程树
		if runtime.GOOS == "windows" {
			_ = exec.Command("taskkill", "/T", "/F", "/PID", strconv.Itoa(p.pid)).Run()
		} else if cmd.Process != nil {
			_ = cmd.Process.Kill()
		}
		<-waitCh
		p.markExited()
		return nil, fmt.Errorf("服务启动超时（%s），未检测到启动标记", startTimeout)
	}
}
