package config

import (
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"raymonitor/logx"
)

type ClusterConfig struct {
	ID          string `json:"id"`
	PlatformURL string `json:"platformUrl"`
}

func (c ClusterConfig) DisplayName() string {
	if c.PlatformURL == "" {
		return c.ID
	}
	u := c.PlatformURL
	for _, p := range []string{"http://", "https://"} {
		if len(u) > len(p) && u[:len(p)] == p {
			u = u[len(p):]
			break
		}
	}
	return u
}

type Thresholds struct {
	NodeCPU   float64 `json:"nodeCpu"`
	NodeMEM   float64 `json:"nodeMem"`
	NodeGPU   float64 `json:"nodeGpu"`
	WorkerCPU float64 `json:"workerCpu"`
	WorkerMEM float64 `json:"workerMem"`
	WorkerGPU float64 `json:"workerGpu"`
}

type Config struct {
	Clusters           []ClusterConfig `json:"clusters"`
	DBPath             string          `json:"dbPath"`
	LogDir             string          `json:"logDir"`
	SortBy             string          `json:"sortBy"`
	SampleEvery        int             `json:"sampleEvery"`
	Thresholds         Thresholds      `json:"thresholds"`
	TimeoutSec         int             `json:"timeoutSec,omitempty"`
	Concurrency        int             `json:"concurrency,omitempty"`
	GlobalConcurrency  int             `json:"globalConcurrency,omitempty"`
	RecoverConsecutive int             `json:"recoverConsecutive,omitempty"`
	RetentionDays      int             `json:"retentionDays,omitempty"`
	CleanupEveryHours  int             `json:"cleanupEveryHours,omitempty"`
}

func Default() Config {
	return Config{
		Clusters: []ClusterConfig{
			{ID: "default", PlatformURL: "http://10.30.144.41:32549"},
		},
		DBPath:             "ray_monitor.db",
		LogDir:             "logs",
		SortBy:             "cpu",
		SampleEvery:        10,
		TimeoutSec:         8,
		Concurrency:        10,
		GlobalConcurrency:  30,
		Thresholds:         DefaultThresholds(),
		RecoverConsecutive: 3,
		RetentionDays:      90,
		CleanupEveryHours:  6,
	}
}

func DefaultThresholds() Thresholds {
	return Thresholds{
		NodeCPU: 80, NodeMEM: 80, NodeGPU: 90,
		WorkerCPU: 80, WorkerMEM: 80, WorkerGPU: 90,
	}
}

func (c *Config) ResolveThresholds(clusterID string) Thresholds {
	return c.Thresholds
}

func (c *Config) SampleInterval() int {
	if c.SampleEvery > 0 {
		return c.SampleEvery
	}
	return 10
}

func (c *Config) EffectiveRetentionDays() int {
	if c.RetentionDays > 0 {
		return c.RetentionDays
	}
	return 90
}

func (c *Config) EffectiveCleanupEveryHours() int {
	if c.CleanupEveryHours > 0 {
		return c.CleanupEveryHours
	}
	return 6
}

func Path() string {
	exe, err := os.Executable()
	if err != nil {
		return "config.json"
	}
	return filepath.Join(filepath.Dir(exe), "config.json")
}

func fallbackPath() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return "config.json"
	}
	return filepath.Join(home, "ray_monitor", "config.json")
}

func ActualPath() string {
	main := Path()
	if _, err := os.Stat(main); err == nil {
		return main
	}
	return fallbackPath()
}

type legacyConfig struct {
	PlatformURL  string `json:"platformUrl"`
	Cookie       string `json:"cookie"`
	SummaryEvery int    `json:"summaryEvery"`
	DetailEvery  int    `json:"detailEvery"`
}

func readConfig() ([]byte, string, error) {
	main := Path()
	if b, err := os.ReadFile(main); err == nil {
		return b, main, nil
	}
	fb := fallbackPath()
	b, err := os.ReadFile(fb)
	return b, fb, err
}

func Load() (Config, error) {
	b, p, err := readConfig()
	if err != nil && os.IsNotExist(err) {
		cfg := Default()
		_ = Save(cfg)
		return cfg, nil
	}
	if err != nil {
		return Default(), err
	}

	var cfg Config
	if err := json.Unmarshal(b, &cfg); err != nil {
		return Default(), err
	}

	if len(cfg.Clusters) == 0 {
		var leg legacyConfig
		if json.Unmarshal(b, &leg) == nil && leg.PlatformURL != "" {
			cfg = migrateFromLegacy(b)
			logx.L().Info("migrated legacy v1 config to v2 clusters", "url", leg.PlatformURL)
			_ = Save(cfg)
		}
	}
	_ = p

	if len(cfg.Clusters) == 0 {
		cfg.Clusters = Default().Clusters
	}
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
	if cfg.RetentionDays <= 0 {
		cfg.RetentionDays = 90
	}
	if cfg.CleanupEveryHours <= 0 {
		cfg.CleanupEveryHours = 6
	}
	return cfg, nil
}

func migrateFromLegacy(b []byte) Config {
	var leg legacyConfig
	_ = json.Unmarshal(b, &leg)
	var cfg Config
	_ = json.Unmarshal(b, &cfg)

	if len(cfg.Clusters) == 0 && leg.PlatformURL != "" {
		cfg.Clusters = []ClusterConfig{{ID: "default", PlatformURL: leg.PlatformURL}}
	} else {
		for i, cl := range cfg.Clusters {
			cfg.Clusters[i] = ClusterConfig{ID: cl.ID, PlatformURL: cl.PlatformURL}
			if cfg.Clusters[i].ID == "" {
				cfg.Clusters[i].ID = fmt.Sprintf("cluster-%d", i)
			}
		}
	}

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
	if cfg.RetentionDays == 0 {
		cfg.RetentionDays = 90
	}
	if cfg.CleanupEveryHours == 0 {
		cfg.CleanupEveryHours = 6
	}
	return cfg
}

func Save(cfg Config) error {
	b, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}
	if err := atomicWrite(Path(), b); err == nil {
		return nil
	}
	fb := fallbackPath()
	if err := os.MkdirAll(filepath.Dir(fb), 0o755); err != nil {
		return err
	}
	if err := atomicWrite(fb, b); err != nil {
		return err
	}
	logx.L().Info("config saved to fallback path (exe dir not writable)", "path", fb)
	return nil
}

func atomicWrite(path string, data []byte) error {
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, ".config-*.tmp")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	defer func() {
		tmp.Close()
		os.Remove(tmpName)
	}()
	if _, err := tmp.Write(data); err != nil {
		return err
	}
	if err := tmp.Sync(); err != nil {
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmpName, path)
}

func SaveClusters(clusters []ClusterConfig) error {
	cfg, err := Load()
	if err != nil {
		return fmt.Errorf("load before save clusters: %w", err)
	}
	cfg.Clusters = clusters
	return Save(cfg)
}

func Validate(cfg Config) error {
	if cfg.SampleEvery < 1 || cfg.SampleEvery > 3600 {
		return fmt.Errorf("sampleEvery must be 1~3600")
	}
	if cfg.TimeoutSec < 1 || cfg.TimeoutSec > 300 {
		return fmt.Errorf("timeoutSec must be 1~300")
	}
	if cfg.Concurrency < 1 || cfg.Concurrency > 1000 {
		return fmt.Errorf("concurrency must be 1~1000")
	}
	if cfg.GlobalConcurrency < 1 || cfg.GlobalConcurrency > 5000 {
		return fmt.Errorf("globalConcurrency must be 1~5000")
	}
	if cfg.GlobalConcurrency < cfg.Concurrency {
		return fmt.Errorf("globalConcurrency must be >= concurrency")
	}
	if cfg.RecoverConsecutive < 1 || cfg.RecoverConsecutive > 100 {
		return fmt.Errorf("recoverConsecutive must be 1~100")
	}
	if cfg.RetentionDays < 1 || cfg.RetentionDays > 3650 {
		return fmt.Errorf("retentionDays must be 1~3650")
	}

	th := cfg.Thresholds
	for _, v := range []struct {
		name string
		val  float64
	}{
		{"nodeCpu", th.NodeCPU}, {"nodeMem", th.NodeMEM}, {"nodeGpu", th.NodeGPU},
		{"workerCpu", th.WorkerCPU}, {"workerMem", th.WorkerMEM}, {"workerGpu", th.WorkerGPU},
	} {
		if v.val < 0 || v.val > 100 {
			return fmt.Errorf("threshold %s must be 0~100", v.name)
		}
	}

	seenIDs := map[string]bool{}
	seenURLs := map[string]bool{}
	for _, cl := range cfg.Clusters {
		id := strings.TrimSpace(cl.ID)
		if id == "" {
			return fmt.Errorf("cluster id must not be empty")
		}
		if seenIDs[id] {
			return fmt.Errorf("duplicate cluster id: %s", id)
		}
		seenIDs[id] = true

		rawURL := strings.TrimSpace(cl.PlatformURL)
		if rawURL == "" {
			return fmt.Errorf("cluster %s: platform URL must not be empty", id)
		}
		u, err := url.Parse(rawURL)
		if err != nil {
			return fmt.Errorf("cluster %s: invalid URL: %v", id, err)
		}
		if u.Scheme != "http" && u.Scheme != "https" {
			return fmt.Errorf("cluster %s: URL scheme must be http or https", id)
		}
		if u.Host == "" {
			return fmt.Errorf("cluster %s: invalid platform URL: missing host", id)
		}
		normalized := u.Scheme + "://" + u.Host
		if seenURLs[normalized] {
			return fmt.Errorf("cluster %s: duplicate platform URL: %s", id, normalized)
		}
		seenURLs[normalized] = true
	}
	return nil
}

func ResolveRuntimePath(path string, baseDir string) string {
	if filepath.IsAbs(path) {
		return filepath.Clean(path)
	}
	return filepath.Join(baseDir, filepath.Clean(path))
}
