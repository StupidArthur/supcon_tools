// Package logx 提供采集器日志封装（slog）。
//
// 按 runtime-safety 规范：日志与业务逻辑分离，覆盖关键节点
// （采集启动/完成、接口失败、DB 写失败）。输出到控制台 + 文件 ray_monitor.log。
package logx

import (
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
)

var logger *slog.Logger

// Init 初始化全局 logger。logDir 为日志文件目录。
// 返回实际日志文件绝对路径（即使失败也返回尝试的路径），供上层诊断。
// 设计要点：日志初始化本身不能静默失败——若指定目录写不进，
// 回退到用户主目录下的 ray_monitor 目录，确保采集错误一定能落盘可见。
// GUI 模式无控制台，故只写文件（dev 模式 stdout 也无意义且可能阻塞）。
func Init(logDir string) (string, error) {
	f, err := openLogFile(logDir)
	if err != nil {
		return "", err
	}
	logger = slog.New(slog.NewTextHandler(f, &slog.HandlerOptions{Level: slog.LevelDebug}))
	logger.Info("logger initialized", "logFile", f.Name())
	return f.Name(), nil
}

// openLogFile 尝试在 logDir 打开日志文件，失败则回退到用户主目录。
// 相对路径解析为 exe 同目录，避免双击运行时工作目录不确定。
func openLogFile(logDir string) (*os.File, error) {
	if logDir == "" {
		logDir = "logs"
	}
	// 相对路径：解析为 exe 同目录绝对路径
	if !filepath.IsAbs(logDir) {
		if exe, err := os.Executable(); err == nil {
			logDir = filepath.Join(filepath.Dir(exe), logDir)
		}
	}
	if err := os.MkdirAll(logDir, 0o755); err == nil {
		if f, err := os.OpenFile(filepath.Join(logDir, "ray_monitor.log"),
			os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644); err == nil {
			return f, nil
		}
	}
	// 回退：用户主目录
	if home, e := os.UserHomeDir(); e == nil {
		fallback := filepath.Join(home, "ray_monitor")
		_ = os.MkdirAll(fallback, 0o755)
		if f, err := os.OpenFile(filepath.Join(fallback, "ray_monitor.log"),
			os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644); err == nil {
			return f, nil
		}
	}
	return nil, fmt.Errorf("cannot open log file in %s", logDir)
}

// L 返回全局 logger。未 Init 时返回默认控制台 logger，避免 nil panic。
func L() *slog.Logger {
	if logger == nil {
		logger = slog.Default()
	}
	return logger
}
