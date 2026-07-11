// config.go - 应用运行期路径配置(组合根读取)。
package app

import (
	"path/filepath"

	"ua_test_gui/internal/platform"
)

// Config 应用运行期路径配置。
type Config struct {
	DBPath      string // SQLite 库路径
	LogDir      string // 日志目录
	MockWorkDir string // mock 工作目录(写 yaml/log)
}

// DefaultConfig 推导默认路径(~/.ua_test_gui/)。
func DefaultConfig() Config {
	base := filepath.Join(platform.UserHome(), ".ua_test_gui")
	return Config{
		DBPath:      filepath.Join(base, "ua_test_gui.db"),
		LogDir:      filepath.Join(base, "logs"),
		MockWorkDir: filepath.Join(base, "mock_work"),
	}
}
