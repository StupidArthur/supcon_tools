package bindings

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// RecentProjectEntry 表示一个最近打开的工程。
// 持久化到 <EXE 同级目录>/recent_projects.json。
type RecentProjectEntry struct {
	ProjectFile string `json:"projectFile"`
	LastOpened  string `json:"lastOpened"`
}

type recentProjectsFile struct {
	Version int                  `json:"version"`
	Entries []RecentProjectEntry `json:"entries"`
}

var (
	recentMu       sync.Mutex
	recentCache    []RecentProjectEntry
	recentLoaded   bool
	recentMaxCount = 16
)

// recentProjectsFilePath 返回持久化文件的绝对路径。
func recentProjectsFilePath() (string, error) {
	exe, err := ResolveExeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(exe, "recent_projects.json"), nil
}

func loadRecentProjectsLocked() ([]RecentProjectEntry, error) {
	path, err := recentProjectsFilePath()
	if err != nil {
		return nil, err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("读取最近工程文件失败: %w", err)
	}
	var f recentProjectsFile
	if err := json.Unmarshal(data, &f); err != nil {
		// 文件损坏 → 视为空列表，不阻断应用启动。
		return nil, nil
	}
	return f.Entries, nil
}

func saveRecentProjectsLocked(entries []RecentProjectEntry) error {
	path, err := recentProjectsFilePath()
	if err != nil {
		return err
	}
	f := recentProjectsFile{Version: 1, Entries: entries}
	data, err := json.MarshalIndent(f, "", "  ")
	if err != nil {
		return err
	}
	return atomicWriteFile(path, data)
}

func atomicWriteFile(path string, data []byte) error {
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// ListRecentProjects 返回所有最近打开工程列表，按 LastOpened 倒序。
// 过滤掉工程文件不存在的条目；保留顺序稳定。
func (b *RealtimeProjectBinding) ListRecentProjects() ([]RecentProjectEntry, error) {
	recentMu.Lock()
	defer recentMu.Unlock()
	if !recentLoaded {
		entries, err := loadRecentProjectsLocked()
		if err != nil {
			return nil, err
		}
		recentCache = entries
		recentLoaded = true
	}
	filtered := make([]RecentProjectEntry, 0, len(recentCache))
	for _, e := range recentCache {
		if _, err := os.Stat(e.ProjectFile); err == nil {
			filtered = append(filtered, e)
		}
	}
	return cloneEntries(filtered), nil
}

// AddRecentProject 把工程加入最近列表（重复时刷新 LastOpened 并前移）。
func (b *RealtimeProjectBinding) AddRecentProject(projectFile string) error {
	if strings.TrimSpace(projectFile) == "" {
		return fmt.Errorf("projectFile 不能为空")
	}
	abs, err := filepath.Abs(projectFile)
	if err != nil {
		return fmt.Errorf("解析工程路径失败: %w", err)
	}
	if _, err := os.Stat(abs); err != nil {
		return fmt.Errorf("工程文件不存在: %w", err)
	}
	recentMu.Lock()
	defer recentMu.Unlock()
	if !recentLoaded {
		entries, _ := loadRecentProjectsLocked()
		recentCache = entries
		recentLoaded = true
	}
	next := []RecentProjectEntry{{ProjectFile: abs, LastOpened: time.Now().UTC().Format(time.RFC3339)}}
	for _, e := range recentCache {
		if strings.EqualFold(e.ProjectFile, abs) {
			continue
		}
		next = append(next, e)
	}
	if len(next) > recentMaxCount {
		next = next[:recentMaxCount]
	}
	recentCache = next
	return saveRecentProjectsLocked(recentCache)
}

// RemoveRecentProject 从最近列表移除指定工程文件。
func (b *RealtimeProjectBinding) RemoveRecentProject(projectFile string) error {
	if strings.TrimSpace(projectFile) == "" {
		return fmt.Errorf("projectFile 不能为空")
	}
	abs, err := filepath.Abs(projectFile)
	if err != nil {
		return err
	}
	recentMu.Lock()
	defer recentMu.Unlock()
	if !recentLoaded {
		entries, _ := loadRecentProjectsLocked()
		recentCache = entries
		recentLoaded = true
	}
	out := make([]RecentProjectEntry, 0, len(recentCache))
	for _, e := range recentCache {
		if !strings.EqualFold(e.ProjectFile, abs) {
			out = append(out, e)
		}
	}
	recentCache = out
	return saveRecentProjectsLocked(recentCache)
}

func cloneEntries(in []RecentProjectEntry) []RecentProjectEntry {
	out := make([]RecentProjectEntry, len(in))
	copy(out, in)
	return out
}