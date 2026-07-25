package bindings

import (
	"errors"
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
// 该函数只解析路径，不创建目录。EnsureAppWorkspaceDirs 负责创建。
func ResolveTemplateDir() (string, error) {
	exe, err := ResolveExeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(exe, "template"), nil
}

// ResolveProjectsRootDir 返回 EXE 同级目录下的 project/ 绝对路径。
// 工程总体文件统一存放在 <exe>/project/<工程名>/project.yaml。
// 该函数只解析路径，不创建目录。EnsureAppWorkspaceDirs 负责创建。
func ResolveProjectsRootDir() (string, error) {
	exe, err := ResolveExeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(exe, "project"), nil
}

// AppWorkspacePaths 描述应用工作目录三件套（EXE 目录 + project + template）。
// 所有路径都是绝对路径。EnsureAppWorkspaceDirs 负责创建缺失的目录。
type AppWorkspacePaths struct {
	ExeDir      string
	ProjectDir  string
	TemplateDir string
}

// EnsureAppWorkspaceDirs 确保 EXE 同级目录下的 project/ 和 template/ 存在。
//
// 行为：
//   - 路径全部基于 os.Executable() 解析的 EXE 目录；
//   - 目录不存在时用 os.MkdirAll 创建；
//   - 目录已存在时直接使用，不清空、不覆盖；
//   - 路径存在但不是目录（同名普通文件占用）时返回明确错误；
//   - 无权限创建时返回包含实际路径的中文错误；
//   - 不在 template/ 中自动生成示例文件，不在 project/ 中自动生成工程；
//   - 不使用当前工作目录或用户配置目录作为替代路径。
//
// 调用时机：应用启动（OnStartup）调用一次即可，与用户是否点击"新建工程"无关。
// 后续 ChooseProjectFile / ChooseYamlForDsl 在显示文件选择器前也会再调用一次以兜底。
func EnsureAppWorkspaceDirs() (AppWorkspacePaths, error) {
	exe, err := ResolveExeDir()
	if err != nil {
		return AppWorkspacePaths{}, err
	}
	projectDir := filepath.Join(exe, "project")
	templateDir := filepath.Join(exe, "template")

	if err := ensureDirIsCreatable(projectDir); err != nil {
		return AppWorkspacePaths{}, fmt.Errorf("project 目录不可用 (%s): %w", projectDir, err)
	}
	if err := ensureDirIsCreatable(templateDir); err != nil {
		return AppWorkspacePaths{}, fmt.Errorf("template 目录不可用 (%s): %w", templateDir, err)
	}

	return AppWorkspacePaths{
		ExeDir:      exe,
		ProjectDir:  projectDir,
		TemplateDir: templateDir,
	}, nil
}

// ensureDirIsCreatable 确保路径是目录（必要时创建）。
//
// 规则：
//   - 路径不存在 → 创建；
//   - 路径存在且是目录 → 视为已存在，no-op；
//   - 路径存在但是普通文件 / 符号链接等 → 返回明确错误；
//   - 创建失败 → 返回带路径的中文错误。
func ensureDirIsCreatable(path string) error {
	info, err := os.Stat(path)
	if err == nil {
		if info.IsDir() {
			return nil
		}
		return fmt.Errorf("路径已存在但不是目录（同名文件占用）")
	}
	if !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("stat 失败: %w", err)
	}
	if mkErr := os.MkdirAll(path, 0o755); mkErr != nil {
		return fmt.Errorf("创建目录失败: %w", mkErr)
	}
	return nil
}

// EnsureProjectsRootDir 在 EXE 同级目录创建 project/（保留旧 API 兼容）。
// 新代码应优先使用 EnsureAppWorkspaceDirs。
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

// EnsureTemplateDir 在 EXE 同级目录创建 template/。
// 新代码应优先使用 EnsureAppWorkspaceDirs。
func EnsureTemplateDir() (string, error) {
	root, err := ResolveTemplateDir()
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(root, 0o755); err != nil {
		return "", fmt.Errorf("创建 template 目录失败: %w", err)
	}
	return root, nil
}