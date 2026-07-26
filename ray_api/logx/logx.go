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
	"strings"
	"sync"
	"time"
)

var (
	logger         *slog.Logger
	legacy         *os.File
	observationDir string
	logMu          sync.Mutex
	logFiles       = map[string]*dimensionLog{}
	nowFunc        = time.Now
)

type dimensionLog struct {
	date   string
	file   *os.File
	logger *slog.Logger
}

var validDimensions = map[string]bool{
	"app": true, "api": true, "environment": true, "collection": true, "error": true,
}

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
	logMu.Lock()
	if legacy != nil {
		_ = legacy.Close()
	}
	legacy = f
	observationDir = filepath.Dir(f.Name())
	logMu.Unlock()
	pruneObservationLogs(observationDir, nowFunc().AddDate(0, 0, -30))
	logger.Info("logger initialized", "logFile", f.Name())
	Event("app", "logger_initialized", "log_dir", observationDir, "retention_days", 30)
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

// Event writes a structured JSONL event to a dimension-specific daily file.
// Dimension names are fixed so callers cannot create arbitrary paths.
func Event(dimension, message string, attrs ...any) {
	if !validDimensions[dimension] {
		dimension = "app"
	}
	logMu.Lock()
	defer logMu.Unlock()
	if observationDir == "" {
		return
	}
	now := nowFunc()
	date := now.Format("2006-01-02")
	entry := logFiles[dimension]
	if entry == nil || entry.date != date {
		if entry != nil && entry.file != nil {
			_ = entry.file.Close()
		}
		path := filepath.Join(observationDir, dimension+"_"+date+".jsonl")
		file, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
		if err != nil {
			L().Warn("open observation log failed", "dimension", dimension, "err", err)
			delete(logFiles, dimension)
			return
		}
		entry = &dimensionLog{
			date:   date,
			file:   file,
			logger: slog.New(slog.NewJSONHandler(file, &slog.HandlerOptions{Level: slog.LevelDebug})),
		}
		logFiles[dimension] = entry
	}
	entry.logger.Info(message, attrs...)
}

func Close() {
	logMu.Lock()
	defer logMu.Unlock()
	for name, entry := range logFiles {
		if entry.file != nil {
			_ = entry.file.Close()
		}
		delete(logFiles, name)
	}
	if legacy != nil {
		_ = legacy.Close()
		legacy = nil
	}
}

func pruneObservationLogs(dir string, before time.Time) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		matched := false
		for dimension := range validDimensions {
			if strings.HasPrefix(name, dimension+"_") && strings.HasSuffix(name, ".jsonl") {
				matched = true
				break
			}
		}
		if !matched {
			continue
		}
		info, err := entry.Info()
		if err == nil && info.ModTime().Before(before) {
			_ = os.Remove(filepath.Join(dir, name))
		}
	}
}
