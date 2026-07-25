package bindings

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
)

// exeDirCache 缓存 os.Executable() 解析结果，避免每次都重复解析。
// 在容器/绑定过程中其他 binding 会通过 ResolveExeDir() 取值，统一返回同一绝对路径。
//
// 测试可通过赋值 exeDirOverrideForTest + 重置 exeDirOnce 来覆盖。
var (
	exeDirOnce  sync.Once
	exeDirValue string
	exeDirErr   error
)

// exeDirOverrideForTest 为测试注入的 EXE 目录覆盖值；非空时跳过 os.Executable。
// 生产代码不会设置此变量。
var exeDirOverrideForTest string

// ResolveExeDir 返回当前可执行文件所在目录的绝对路径。
//
// 设计文档 §三"路径统一规则"：所有默认路径都以 EXE 所在目录为基准，
// 不依赖当前工作目录、用户配置目录、源代码目录或临时构建目录。
//
// 实现：调用 os.Executable()，再取 filepath.Dir；返回绝对路径。
// 该函数在进程生命周期内仅解析一次，结果缓存。
func ResolveExeDir() (string, error) {
	exeDirOnce.Do(func() {
		if v := exeDirOverrideForTest; v != "" {
			abs, err := filepath.Abs(v)
			if err != nil {
				exeDirErr = fmt.Errorf("解析测试 EXE 目录失败: %w", err)
				return
			}
			exeDirValue = abs
			return
		}
		exePath, err := os.Executable()
		if err != nil {
			exeDirErr = fmt.Errorf("获取可执行文件路径失败: %w", err)
			return
		}
		abs, err := filepath.Abs(filepath.Dir(exePath))
		if err != nil {
			exeDirErr = fmt.Errorf("解析 EXE 目录失败: %w", err)
			return
		}
		exeDirValue = abs
	})
	return exeDirValue, exeDirErr
}

// ResolveTemplateDir 返回 EXE 同级目录下的 template/ 绝对路径。
// 目录不存在时按需创建（仅在确实被请求时创建，避免污染用户工作目录）。
func ResolveTemplateDir() (string, error) {
	exe, err := ResolveExeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(exe, "template"), nil
}

// ResolveProjectsRootDir 返回 EXE 同级目录下的 project/ 绝对路径。
// 工程总体文件统一存放在 <exe>/project/<工程名>/project.yaml。
func ResolveProjectsRootDir() (string, error) {
	exe, err := ResolveExeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(exe, "project"), nil
}

// EnsureProjectsRootDir 在 EXE 同级目录创建 project/。
// 调用方应在调用 CreateProjectAt 之前确保父目录存在。
func EnsureProjectsRootDir() (string, error) {
	root, err := ResolveProjectsRootDir()
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(root, 0o755); err != nil {
		return "", fmt.Errorf("创建 project 目录失败: %w", err)
	}
	return root, nil
}