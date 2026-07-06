// Package config 持久化非敏感的登录配置（URL + 租户 ID），不存密码。
//
// 路径：$HOME/.user-manager/config.json
// 格式：JSON
//
// 设计依据：doc/design.md §3.1（LoginConfig 持久化）、§4 分歧 3（推荐方案）
package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

// FileName 是 config 文件名。
const FileName = "config.json"

// DirName 是配置目录名（拼到 $HOME 下）。
const DirName = ".user-manager"

// Config 是持久化的配置项。
type Config struct {
	URL      string `json:"url"`
	TenantID string `json:"tenantId"`
}

// configPath 返回 config.json 完整路径。
func configPath() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("get home dir: %w", err)
	}
	return filepath.Join(home, DirName, FileName), nil
}

// Load 读 config.json。文件不存在返回空 Config + nil error。
func Load() (*Config, error) {
	path, err := configPath()
	if err != nil {
		return nil, err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return &Config{}, nil
		}
		return nil, fmt.Errorf("read config: %w", err)
	}
	var c Config
	if err := json.Unmarshal(data, &c); err != nil {
		return nil, fmt.Errorf("decode config: %w", err)
	}
	return &c, nil
}

// Save 写 config.json。自动创建目录。
func Save(c *Config) error {
	if c == nil {
		return errors.New("config is nil")
	}
	path, err := configPath()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("mkdir: %w", err)
	}
	data, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return fmt.Errorf("encode config: %w", err)
	}
	if err := os.WriteFile(path, data, 0o600); err != nil { // 0o600：仅 owner 读写
		return fmt.Errorf("write config: %w", err)
	}
	return nil
}

// Clear 删除 config.json（登出时调用）。
func Clear() error {
	path, err := configPath()
	if err != nil {
		return err
	}
	if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}
