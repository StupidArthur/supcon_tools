package realtime

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/google/uuid"
	"gopkg.in/yaml.v3"
)

type DashboardWidget struct {
	ID      string                 `json:"id" yaml:"id"`
	Type    string                 `json:"type" yaml:"type"`
	Tag     string                 `json:"tag" yaml:"tag"`
	X       int                    `json:"x" yaml:"x"`
	Y       int                    `json:"y" yaml:"y"`
	W       int                    `json:"w" yaml:"w"`
	H       int                    `json:"h" yaml:"h"`
	Options map[string]any         `json:"options" yaml:"options"`
}

type DashboardPage struct {
	ID      string            `json:"id" yaml:"id"`
	Name    string            `json:"name" yaml:"name"`
	Widgets []DashboardWidget `json:"widgets" yaml:"widgets"`
}

type Dashboard struct {
	Version int             `json:"version" yaml:"version"`
	Pages   []DashboardPage `json:"pages" yaml:"pages"`
}

var validWidgetTypes = map[string]bool{
	"value":      true,
	"gauge":      true,
	"lamp":       true,
	"trend":      true,
	"write":      true,
	"alarm-list": true,
	"text":       true,
}

func ValidateDashboard(d Dashboard) error {
	pageIDs := map[string]bool{}
	for _, p := range d.Pages {
		if p.ID == "" {
			return fmt.Errorf("页面 ID 不能为空")
		}
		if pageIDs[p.ID] {
			return fmt.Errorf("页面 ID 重复: %s", p.ID)
		}
		pageIDs[p.ID] = true
		widgetIDs := map[string]bool{}
		for _, w := range p.Widgets {
			if w.ID == "" {
				return fmt.Errorf("组件 ID 不能为空")
			}
			if widgetIDs[w.ID] {
				return fmt.Errorf("组件 ID 重复: %s", w.ID)
			}
			widgetIDs[w.ID] = true
			if !validWidgetTypes[w.Type] {
				return fmt.Errorf("非法组件类型: %s", w.Type)
			}
			if w.W <= 0 || w.H <= 0 {
				return fmt.Errorf("组件尺寸必须为正: %s", w.ID)
			}
		}
	}
	return nil
}

func (s *ProjectStorage) dashboardFilePath(projectID string) string {
	return filepath.Join(s.projectDir(projectID), "dashboard.yaml")
}

func (s *ProjectStorage) LoadDashboard(projectID string) (Dashboard, error) {
	path := s.dashboardFilePath(projectID)
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return Dashboard{Version: 1, Pages: []DashboardPage{}}, nil
		}
		return Dashboard{}, err
	}
	var d Dashboard
	if err := yaml.Unmarshal(data, &d); err != nil {
		return Dashboard{}, fmt.Errorf("解析 dashboard.yaml 失败: %w", err)
	}
	if d.Pages == nil {
		d.Pages = []DashboardPage{}
	}
	return d, nil
}

func (s *ProjectStorage) SaveDashboard(projectID string, d Dashboard) error {
	if d.Version == 0 {
		d.Version = 1
	}
	if d.Pages == nil {
		d.Pages = []DashboardPage{}
	}
	data, err := yaml.Marshal(d)
	if err != nil {
		return err
	}
	return atomicWrite(s.dashboardFilePath(projectID), data)
}

func (m *Manager) GetDashboard(_ context.Context, projectID string) (Dashboard, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, err := m.storage.LoadProject(projectID); err != nil {
		return Dashboard{}, err
	}
	return m.storage.LoadDashboard(projectID)
}

func (m *Manager) SaveDashboard(_ context.Context, projectID string, d Dashboard) (Dashboard, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, err := m.storage.LoadProject(projectID); err != nil {
		return Dashboard{}, err
	}
	if err := ValidateDashboard(d); err != nil {
		return Dashboard{}, err
	}
	if err := m.storage.SaveDashboard(projectID, d); err != nil {
		return Dashboard{}, err
	}
	return d, nil
}

// NewDashboardID generates a stable ID for pages/widgets.
func NewDashboardID() string {
	return uuid.New().String()
}
