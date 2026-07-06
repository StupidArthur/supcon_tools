// Package config 管理采集器配置。
//
// v2 支持多集群：Clusters 列表 + 全局配置 + 两级阈值（全局 + 集群覆盖）。
// 配置以 JSON 文件持久化到 exe 同级 config.json，前端可读写。
// 旧格式（v1 单 platformUrl）启动时自动迁移为 Clusters[0]，确保无感升级。
package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"raymonitor/logx"
)

// ClusterConfig 单个集群配置。集群只填 URL，URL 即集群名。
// 其他项（采样间隔/阈值）统一在全局配置，不按集群单独配。
type ClusterConfig struct {
	ID          string `json:"id"`          // 唯一标识
	PlatformURL string `json:"platformUrl"` // 集群地址，同时作为显示名
}

// DisplayName 集群显示名：取 URL 的 host:port，便于侧边栏展示。
func (c ClusterConfig) DisplayName() string {
	if c.PlatformURL == "" {
		return c.ID
	}
	// 去掉协议前缀
	u := c.PlatformURL
	for _, p := range []string{"http://", "https://"} {
		if len(u) > len(p) && u[:len(p)] == p {
			u = u[len(p):]
			break
		}
	}
	return u
}

// Thresholds 阈值（百分比 0~100）。
type Thresholds struct {
	NodeCPU   float64 `json:"nodeCpu"`
	NodeMEM   float64 `json:"nodeMem"`
	NodeGPU   float64 `json:"nodeGpu"`
	WorkerCPU float64 `json:"workerCpu"`
	WorkerMEM float64 `json:"workerMem"`
	WorkerGPU float64 `json:"workerGpu"`
}

// Config 全局配置。共享项在此，集群只填 URL。
type Config struct {
	Clusters          []ClusterConfig `json:"clusters"`          // 集群列表（每项只有 URL）
	DBPath            string          `json:"dbPath"`            // SQLite 路径
	LogDir            string          `json:"logDir"`            // 日志目录
	SortBy            string          `json:"sortBy"`            // 列表排序：cpu | gpu
	SampleEvery       int             `json:"sampleEvery"`       // 统一采样间隔（秒），summary 和 detail 共用，默认 10
	Thresholds        Thresholds      `json:"thresholds"`        // 全局报警阈值
	// 以下字段后端使用，前端不暴露（用默认值）
	TimeoutSec         int `json:"timeoutSec,omitempty"`
	Concurrency        int `json:"concurrency,omitempty"`
	GlobalConcurrency  int `json:"globalConcurrency,omitempty"`
	RecoverConsecutive int `json:"recoverConsecutive,omitempty"`
}

// Default 返回默认配置。含一个默认集群（对应当前参照环境）。
func Default() Config {
	return Config{
		Clusters: []ClusterConfig{
			{ID: "default", PlatformURL: "http://10.30.144.41:32549"},
		},
		DBPath:            "ray_monitor.db",
		LogDir:            "logs",
		SortBy:            "cpu",
		SampleEvery:       10,
		TimeoutSec:        8,
		Concurrency:       10,
		GlobalConcurrency:  30,
		Thresholds:         DefaultThresholds(),
		RecoverConsecutive: 3,
	}
}

// DefaultThresholds 默认阈值（百分比）。CPU/MEM 80%，GPU 90%。
func DefaultThresholds() Thresholds {
	return Thresholds{
		NodeCPU: 80, NodeMEM: 80, NodeGPU: 90,
		WorkerCPU: 80, WorkerMEM: 80, WorkerGPU: 90,
	}
}

// ResolveThresholds 阈值统一用全局（集群不再单独配）。
func (c *Config) ResolveThresholds(clusterID string) Thresholds {
	return c.Thresholds
}

// SampleInterval 统一采样间隔（秒），summary 和 detail 共用。非正则兜底 10。
func (c *Config) SampleInterval() int {
	if c.SampleEvery > 0 {
		return c.SampleEvery
	}
	return 10
}

// Path 配置文件主路径：与可执行文件同目录。
func Path() string {
	exe, err := os.Executable()
	if err != nil {
		return "config.json"
	}
	return filepath.Join(filepath.Dir(exe), "config.json")
}

// fallbackPath 回退路径：用户主目录下 ray_monitor/config.json。
// 当 exe 所在目录无写权限（如 Program Files）时，配置写这里。
func fallbackPath() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return "config.json"
	}
	return filepath.Join(home, "ray_monitor", "config.json")
}

// actualPath 返回配置实际所在的路径（优先主路径，不存在则回退路径）。
// 供 app 层显示给用户。
func ActualPath() string {
	main := Path()
	if _, err := os.Stat(main); err == nil {
		return main
	}
	return fallbackPath()
}

// v1 旧配置结构，仅用于迁移检测。
type legacyConfig struct {
	PlatformURL  string `json:"platformUrl"`
	Cookie       string `json:"cookie"`
	SummaryEvery int    `json:"summaryEvery"`
	DetailEvery  int    `json:"detailEvery"`
}

// readConfig 优先读主路径，失败再读回退路径。返回内容、实际路径、错误。
func readConfig() ([]byte, string, error) {
	main := Path()
	if b, err := os.ReadFile(main); err == nil {
		return b, main, nil
	}
	fb := fallbackPath()
	b, err := os.ReadFile(fb)
	return b, fb, err
}

// Load 读取配置文件。不存在则写默认；检测到 v1 旧格式则迁移为 Clusters[0]。
func Load() (Config, error) {
	// 优先读主路径，读不到（不存在或无权限）再读回退路径
	b, p, err := readConfig()
	if err != nil && os.IsNotExist(err) {
		// 两处都不存在：首次运行，落默认配置（写到能写的位置）
		cfg := Default()
		_ = Save(cfg)
		return cfg, nil
	}
	if err != nil {
		return Default(), err
	}

	// 先尝试按 v2 解析
	var cfg Config
	if err := json.Unmarshal(b, &cfg); err != nil {
		return Default(), err
	}

	// 迁移检测：v1 旧格式有顶层 platformUrl 且无 clusters
	if len(cfg.Clusters) == 0 {
		var leg legacyConfig
		if json.Unmarshal(b, &leg) == nil && leg.PlatformURL != "" {
			cfg = migrateFromLegacy(b)
			logx.L().Info("migrated legacy v1 config to v2 clusters", "url", leg.PlatformURL)
			_ = Save(cfg) // 持久化迁移结果
		}
	}
	_ = p // p 为实际读取的路径，调试可记

	// 兜底：clusters 仍为空则补默认
	if len(cfg.Clusters) == 0 {
		cfg.Clusters = Default().Clusters
	}
	// 兜底默认值
	if cfg.TimeoutSec <= 0 {
		cfg.TimeoutSec = 8
	}
	if cfg.Concurrency <= 0 {
		cfg.Concurrency = 10
	}
	if cfg.GlobalConcurrency <= 0 {
		cfg.GlobalConcurrency = 30
	}
	if cfg.RecoverConsecutive <= 0 {
		cfg.RecoverConsecutive = 3
	}
	if cfg.SortBy == "" {
		cfg.SortBy = "cpu"
	}
	return cfg, nil
}

// migrateFromLegacy 把 v1/v2旧 单集群配置迁移为简化格式（集群只填 URL）。
// v1 的 summaryEvery/detailEvery 合并为全局 SampleEvery。
func migrateFromLegacy(b []byte) Config {
	var leg legacyConfig
	_ = json.Unmarshal(b, &leg)
	var cfg Config
	_ = json.Unmarshal(b, &cfg) // 保留 v2 全局字段（dbPath/logDir/thresholds 等）

	// 集群只保留 URL（兼容旧的 clusters 数组里的 platformUrl，或 v1 顶层 platformUrl）
	if len(cfg.Clusters) == 0 && leg.PlatformURL != "" {
		cfg.Clusters = []ClusterConfig{{ID: "default", PlatformURL: leg.PlatformURL}}
	} else {
		// 已有 clusters：剥离非 URL 字段
		for i, cl := range cfg.Clusters {
			cfg.Clusters[i] = ClusterConfig{ID: cl.ID, PlatformURL: cl.PlatformURL}
			if cfg.Clusters[i].ID == "" {
				cfg.Clusters[i].ID = fmt.Sprintf("cluster-%d", i)
			}
		}
	}

	// 采样间隔迁移到全局：取 v1 summaryEvery（兼容旧 detailEvery）
	if cfg.SampleEvery == 0 {
		if leg.SummaryEvery > 0 {
			cfg.SampleEvery = leg.SummaryEvery
		} else if leg.DetailEvery > 0 {
			cfg.SampleEvery = leg.DetailEvery
		} else {
			cfg.SampleEvery = 10
		}
	}
	if cfg.Thresholds == (Thresholds{}) {
		cfg.Thresholds = DefaultThresholds()
	}
	if cfg.RecoverConsecutive == 0 {
		cfg.RecoverConsecutive = 3
	}
	if cfg.GlobalConcurrency == 0 {
		cfg.GlobalConcurrency = 30
	}
	if cfg.Concurrency == 0 {
		cfg.Concurrency = 10
	}
	if cfg.TimeoutSec == 0 {
		cfg.TimeoutSec = 8
	}
	return cfg
}

// Save 写入配置文件。先写主路径（exe 同目录），失败（如目录无写权限）则回退到用户目录。
func Save(cfg Config) error {
	b, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}
	// 先尝试主路径
	if err := os.WriteFile(Path(), b, 0o644); err == nil {
		return nil
	}
	// 回退到用户目录
	fb := fallbackPath()
	if err := os.MkdirAll(filepath.Dir(fb), 0o755); err != nil {
		return err
	}
	if err := os.WriteFile(fb, b, 0o644); err != nil {
		return err
	}
	logx.L().Info("config saved to fallback path (exe dir not writable)", "path", fb)
	return nil
}

// SaveClusters 仅更新集群列表（热增减时用，避免覆盖运行中可能变更的全局字段）。
func SaveClusters(clusters []ClusterConfig) error {
	cfg, err := Load()
	if err != nil {
		return fmt.Errorf("load before save clusters: %w", err)
	}
	cfg.Clusters = clusters
	return Save(cfg)
}
