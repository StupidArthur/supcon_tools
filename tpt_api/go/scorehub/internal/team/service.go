package team

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
)

//go:embed config.json
var embeddedConfig []byte

// LoadConfig 优先读 exe 同目录的 config.json（方便用户修改），
// 不存在时回退到编译时 embed 的默认配置。
func LoadConfig() (*Config, error) {
	if exe, err := os.Executable(); err == nil {
		p := filepath.Join(filepath.Dir(exe), "config.json")
		if data, err := os.ReadFile(p); err == nil {
			var cfg Config
			if err := json.Unmarshal(data, &cfg); err == nil {
				return &cfg, nil
			}
		}
	}
	var cfg Config
	if err := json.Unmarshal(embeddedConfig, &cfg); err != nil {
		return nil, fmt.Errorf("parse embedded config: %w", err)
	}
	return &cfg, nil
}

// OrderedEnvs 返回与 ListTeams 相同顺序的租户指针切片：
// 选手按 zkjs 升序在前（序号 1~39），测试租户放最后（序号 40~41）。
func OrderedEnvs(cfg *Config) []*Env {
	var players, tests []*Env
	for i := range cfg.Environments {
		e := &cfg.Environments[i]
		if e.Type == "测试" {
			tests = append(tests, e)
		} else {
			players = append(players, e)
		}
	}
	sort.SliceStable(players, func(i, j int) bool {
		return players[i].Zkjs < players[j].Zkjs
	})
	return append(players, tests...)
}

// ListTeams 返回排序后的租户列表。
// 选手按 zkjs 升序排在前（序号 1~39），测试租户放最后（序号 40~41）。
func ListTeams(cfg *Config) []Team {
	var players, tests []Env
	for _, e := range cfg.Environments {
		if e.Type == "测试" {
			tests = append(tests, e)
		} else {
			players = append(players, e)
		}
	}
	sort.SliceStable(players, func(i, j int) bool {
		return players[i].Zkjs < players[j].Zkjs
	})

	ordered := append(players, tests...)
	teams := make([]Team, len(ordered))
	for i, e := range ordered {
		teams[i] = Team{
			Seq:      i + 1,
			Name:     e.Name,
			TenantID: e.TenantID,
			Username: e.Username,
			Machine: Machine{
				Zkjs:    e.Zkjs,
				CloudID: e.CloudID,
			},
			IP:   e.IPv4,
			Type: e.Type,
		}
	}
	return teams
}
