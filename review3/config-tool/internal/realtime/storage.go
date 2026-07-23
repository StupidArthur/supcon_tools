package realtime

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
)

type ProjectStorage struct {
	root string
}

func NewProjectStorage(root string) *ProjectStorage {
	return &ProjectStorage{root: root}
}

func (s *ProjectStorage) Root() string {
	return s.root
}

func (s *ProjectStorage) projectDir(id string) string {
	return filepath.Join(s.root, id)
}

func (s *ProjectStorage) projectFile(id string) string {
	return filepath.Join(s.root, id, "project.yaml")
}

func (s *ProjectStorage) sourcesDir(id string) string {
	return filepath.Join(s.root, id, "sources")
}

func (s *ProjectStorage) sourceFile(projectID, sourceID string) string {
	return filepath.Join(s.root, projectID, "sources", sourceID+".yaml")
}

func (s *ProjectStorage) EnsureRoot() error {
	return os.MkdirAll(s.root, 0o755)
}

func (s *ProjectStorage) ListProjects() ([]ProjectSummary, error) {
	if err := s.EnsureRoot(); err != nil {
		return nil, err
	}
	entries, err := os.ReadDir(s.root)
	if err != nil {
		return nil, err
	}
	var summaries []ProjectSummary
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		if strings.HasPrefix(entry.Name(), ".") {
			continue
		}
		p, err := s.LoadProject(entry.Name())
		if err != nil {
			continue
		}
		summaries = append(summaries, ProjectSummary{
			ID:          p.ID,
			Name:        p.Name,
			SourceCount: len(p.Sources),
		})
	}
	if summaries == nil {
		summaries = []ProjectSummary{}
	}
	return summaries, nil
}

func (s *ProjectStorage) LoadProject(id string) (Project, error) {
	if !isValidID(id) {
		return Project{}, fmt.Errorf("非法工程 ID: %q", id)
	}
	data, err := os.ReadFile(s.projectFile(id))
	if err != nil {
		return Project{}, fmt.Errorf("读取工程失败: %w", err)
	}
	var p Project
	if err := yaml.Unmarshal(data, &p); err != nil {
		return Project{}, fmt.Errorf("解析 project.yaml 失败: %w", err)
	}
	return p, nil
}

func (s *ProjectStorage) SaveProject(p Project) error {
	if !isValidID(p.ID) {
		return fmt.Errorf("非法工程 ID: %q", p.ID)
	}
	dir := s.projectDir(p.ID)
	if err := os.MkdirAll(filepath.Join(dir, "sources"), 0o755); err != nil {
		return err
	}
	return atomicWriteYAML(s.projectFile(p.ID), p)
}

func (s *ProjectStorage) DeleteProject(id string) error {
	if !isValidID(id) {
		return fmt.Errorf("非法工程 ID: %q", id)
	}
	dir := s.projectDir(id)
	if _, err := os.Stat(dir); os.IsNotExist(err) {
		return fmt.Errorf("工程不存在: %s", id)
	}
	trash := filepath.Join(s.root, fmt.Sprintf(".trash-%s-%d", id, os.Getpid()))
	if err := os.Rename(dir, trash); err != nil {
		return os.RemoveAll(dir)
	}
	return os.RemoveAll(trash)
}

func (s *ProjectStorage) CopySourceFile(projectID, sourceID, srcPath string) error {
	if !isValidID(projectID) || !isValidID(sourceID) {
		return fmt.Errorf("非法 ID")
	}
	data, err := os.ReadFile(srcPath)
	if err != nil {
		return fmt.Errorf("读取源文件失败: %w", err)
	}
	dst := s.sourceFile(projectID, sourceID)
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	tmp := dst + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, dst)
}

func (s *ProjectStorage) RemoveSourceFile(projectID, sourceID string) {
	_ = os.Remove(s.sourceFile(projectID, sourceID))
}

func (s *ProjectStorage) SourceAbsPath(projectID, sourceID string) string {
	return s.sourceFile(projectID, sourceID)
}

func (s *ProjectStorage) ProjectExists(id string) bool {
	_, err := os.Stat(s.projectFile(id))
	return err == nil
}

func atomicWriteYAML(path string, v any) error {
	data, err := yaml.Marshal(v)
	if err != nil {
		return fmt.Errorf("序列化 YAML 失败: %w", err)
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func isValidID(id string) bool {
	if id == "" || len(id) > 128 {
		return false
	}
	for _, r := range id {
		if r == '/' || r == '\\' || r == ':' || r == '*' || r == '?' || r == '"' || r == '<' || r == '>' || r == '|' || r == '.' {
			return false
		}
	}
	if id == ".." || strings.Contains(id, "..") {
		return false
	}
	return true
}
