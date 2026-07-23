package realtime

import (
	"context"
	"fmt"
	"math"
	"os"
	"path/filepath"

	"github.com/google/uuid"
	"gopkg.in/yaml.v3"
)

type AlarmDirection string
type AlarmSeverity string

const (
	DirectionHigh AlarmDirection = "high"
	DirectionLow  AlarmDirection = "low"

	SeverityInfo     AlarmSeverity = "info"
	SeverityWarning  AlarmSeverity = "warning"
	SeverityHigh     AlarmSeverity = "high"
	SeverityCritical AlarmSeverity = "critical"
)

type AlarmRule struct {
	ID           string        `json:"id" yaml:"id"`
	Name         string        `json:"name" yaml:"name"`
	Tag          string        `json:"tag" yaml:"tag"`
	Direction    AlarmDirection `json:"direction" yaml:"direction"`
	Limit        float64       `json:"limit" yaml:"limit"`
	Severity     AlarmSeverity `json:"severity" yaml:"severity"`
	DelaySeconds float64       `json:"delay_seconds" yaml:"delay_seconds"`
	Deadband     float64       `json:"deadband" yaml:"deadband"`
	Enabled      bool          `json:"enabled" yaml:"enabled"`
	Message      string        `json:"message" yaml:"message"`
}

type alarmsFile struct {
	Version int         `yaml:"version"`
	Rules   []AlarmRule `yaml:"rules"`
}

func validDirection(d AlarmDirection) bool {
	return d == DirectionHigh || d == DirectionLow
}

func validSeverity(s AlarmSeverity) bool {
	return s == SeverityInfo || s == SeverityWarning || s == SeverityHigh || s == SeverityCritical
}

// ValidateAlarmRule checks a single rule's fields.
func ValidateAlarmRule(r AlarmRule) error {
	if r.Name == "" {
		return fmt.Errorf("报警名称不能为空")
	}
	if r.Tag == "" {
		return fmt.Errorf("报警位号不能为空")
	}
	if !validDirection(r.Direction) {
		return fmt.Errorf("非法 direction: %s", r.Direction)
	}
	if !validSeverity(r.Severity) {
		return fmt.Errorf("非法 severity: %s", r.Severity)
	}
	if math.IsNaN(r.Limit) || math.IsInf(r.Limit, 0) {
		return fmt.Errorf("limit 必须是有限数")
	}
	if math.IsNaN(r.Deadband) || math.IsInf(r.Deadband, 0) || r.Deadband < 0 {
		return fmt.Errorf("deadband 必须是有限非负数")
	}
	if math.IsNaN(r.DelaySeconds) || math.IsInf(r.DelaySeconds, 0) || r.DelaySeconds < 0 {
		return fmt.Errorf("delay_seconds 必须是有限非负数")
	}
	return nil
}

func (s *ProjectStorage) alarmsFilePath(projectID string) string {
	return filepath.Join(s.projectDir(projectID), "alarms.yaml")
}

func (s *ProjectStorage) LoadAlarms(projectID string) ([]AlarmRule, error) {
	path := s.alarmsFilePath(projectID)
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return []AlarmRule{}, nil
		}
		return nil, err
	}
	var f alarmsFile
	if err := yaml.Unmarshal(data, &f); err != nil {
		return nil, fmt.Errorf("解析 alarms.yaml 失败: %w", err)
	}
	if f.Rules == nil {
		f.Rules = []AlarmRule{}
	}
	return f.Rules, nil
}

func (s *ProjectStorage) SaveAlarms(projectID string, rules []AlarmRule) error {
	if rules == nil {
		rules = []AlarmRule{}
	}
	f := alarmsFile{Version: 1, Rules: rules}
	data, err := yaml.Marshal(f)
	if err != nil {
		return err
	}
	return atomicWrite(s.alarmsFilePath(projectID), data)
}

func (m *Manager) ListAlarmRules(_ context.Context, projectID string) ([]AlarmRule, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, err := m.storage.LoadProject(projectID); err != nil {
		return nil, err
	}
	return m.storage.LoadAlarms(projectID)
}

func (m *Manager) CreateAlarmRule(_ context.Context, projectID string, rule AlarmRule) ([]AlarmRule, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, err := m.storage.LoadProject(projectID); err != nil {
		return nil, err
	}
	if rule.ID == "" {
		rule.ID = uuid.New().String()
	}
	if err := ValidateAlarmRule(rule); err != nil {
		return nil, err
	}
	rules, err := m.storage.LoadAlarms(projectID)
	if err != nil {
		return nil, err
	}
	for _, r := range rules {
		if r.ID == rule.ID {
			return nil, fmt.Errorf("报警 ID 重复: %s", rule.ID)
		}
	}
	rules = append(rules, rule)
	if err := m.storage.SaveAlarms(projectID, rules); err != nil {
		return nil, err
	}
	return rules, nil
}

func (m *Manager) UpdateAlarmRule(_ context.Context, projectID string, rule AlarmRule) ([]AlarmRule, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, err := m.storage.LoadProject(projectID); err != nil {
		return nil, err
	}
	if err := ValidateAlarmRule(rule); err != nil {
		return nil, err
	}
	rules, err := m.storage.LoadAlarms(projectID)
	if err != nil {
		return nil, err
	}
	found := false
	for i := range rules {
		if rules[i].ID == rule.ID {
			rules[i] = rule
			found = true
			break
		}
	}
	if !found {
		return nil, fmt.Errorf("报警不存在: %s", rule.ID)
	}
	if err := m.storage.SaveAlarms(projectID, rules); err != nil {
		return nil, err
	}
	return rules, nil
}

func (m *Manager) DeleteAlarmRule(_ context.Context, projectID, alarmID string) ([]AlarmRule, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, err := m.storage.LoadProject(projectID); err != nil {
		return nil, err
	}
	rules, err := m.storage.LoadAlarms(projectID)
	if err != nil {
		return nil, err
	}
	out := make([]AlarmRule, 0, len(rules))
	found := false
	for _, r := range rules {
		if r.ID == alarmID {
			found = true
			continue
		}
		out = append(out, r)
	}
	if !found {
		return nil, fmt.Errorf("报警不存在: %s", alarmID)
	}
	if err := m.storage.SaveAlarms(projectID, out); err != nil {
		return nil, err
	}
	return out, nil
}

func (m *Manager) ValidateAlarmRules(_ context.Context, projectID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, err := m.storage.LoadProject(projectID); err != nil {
		return err
	}
	rules, err := m.storage.LoadAlarms(projectID)
	if err != nil {
		return err
	}
	seen := map[string]bool{}
	for _, r := range rules {
		if seen[r.ID] {
			return fmt.Errorf("报警 ID 重复: %s", r.ID)
		}
		seen[r.ID] = true
		if err := ValidateAlarmRule(r); err != nil {
			return err
		}
	}
	return nil
}
