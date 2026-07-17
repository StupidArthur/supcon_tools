package api

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
)

// YAMLConfig 是解析后的 DSL 配置（只提取 ParamPanel 需要的字段）
type YAMLConfig struct {
	Clock  ClockSection  `yaml:"clock"`
	Program []ProgramSection `yaml:"program"`
}

type ClockSection struct {
	Mode      string  `yaml:"mode"`
	CycleTime float64 `yaml:"cycle_time"`
}

type ProgramSection struct {
	Name        string         `yaml:"name"`
	Type        string         `yaml:"type"`
	Expression  string         `yaml:"expression"`
	InitArgs    map[string]any `yaml:"init_args"`
	DisplayArgs []string       `yaml:"display_args"`
}

// ParseYAML 解析 YAML 配置文件
func ParseYAML(path string) (YAMLConfig, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return YAMLConfig{}, fmt.Errorf("读取 YAML 失败: %w", err)
	}

	var cfg YAMLConfig
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return YAMLConfig{}, fmt.Errorf("解析 YAML 失败: %w", err)
	}

	// 默认值
	if cfg.Clock.Mode == "" {
		cfg.Clock.Mode = "REALTIME"
	}
	if cfg.Clock.CycleTime == 0 {
		cfg.Clock.CycleTime = 0.5
	}

	return cfg, nil
}

// ListConfigs 扫描指定目录下的 config/ 子目录，返回所有 YAML 文件名
func ListConfigs(baseDir string) ([]string, error) {
	configDir := filepath.Join(baseDir, "config")
	entries, err := os.ReadDir(configDir)
	if err != nil {
		return nil, fmt.Errorf("无法读取 config 目录: %w", err)
	}
	var configs []string
	for _, entry := range entries {
		name := entry.Name()
		if strings.HasSuffix(name, ".yaml") || strings.HasSuffix(name, ".yml") {
			configs = append(configs, name)
		}
	}
	return configs, nil
}
