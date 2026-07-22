package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ResolveRepoRoot 定位 review3 仓库根目录（必须包含内置模板 config/单阀门二阶水箱.yaml）。
//
// 查找顺序：
//  1. 环境变量 SUPCON_TOOL_REPO_ROOT
//  2. 从 os.Executable() 所在目录向上最多 8 层
func ResolveRepoRoot() (string, error) {
	if root := strings.TrimSpace(os.Getenv("SUPCON_TOOL_REPO_ROOT")); root != "" {
		abs, _ := filepath.Abs(root)
		if err := assertBuiltinTemplateUnder(abs); err != nil {
			return "", err
		}
		return abs, nil
	}
	exe, err := os.Executable()
	if err != nil {
		return "", fmt.Errorf("获取可执行文件路径失败: %w", err)
	}
	return resolveRepoRootFrom(filepath.Dir(exe))
}

// ResolveConfigDir 返回仓库根下的 config 目录绝对路径。
func ResolveConfigDir() (string, error) {
	root, err := ResolveRepoRoot()
	if err != nil {
		return "", err
	}
	dir := filepath.Join(root, "config")
	if _, err := os.Stat(dir); err != nil {
		return "", fmt.Errorf("config 目录不可用: %w", err)
	}
	return dir, nil
}

func resolveRepoRootFrom(startDir string) (string, error) {
	dir, err := filepath.Abs(startDir)
	if err != nil {
		return "", fmt.Errorf("解析起始目录失败: %w", err)
	}
	for i := 0; i < 8; i++ {
		if err := assertBuiltinTemplateUnder(dir); err == nil {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return "", fmt.Errorf("无法定位仓库根；请设置 SUPCON_TOOL_REPO_ROOT")
}

func assertBuiltinTemplateUnder(root string) error {
	candidate := filepath.Join(root, BuiltinTemplateRelativePath)
	if _, err := os.Stat(candidate); err != nil {
		return fmt.Errorf("SUPCON_TOOL_REPO_ROOT=%q 不包含 %s", root, BuiltinTemplateRelativePath)
	}
	return nil
}
