package bindings

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"config-tool/internal/config"
)

const (
	envDataFactoryPath = "SUPCON_DATAFACTORY_PATH"
	envPythonPath      = "SUPCON_PYTHON"
	standaloneEntry    = "standalone_main.py"
)

// dataFactoryExec 描述如何启动 DataFactory：可能是 DataFactory.exe，也可能是 python standalone_main.py。
type dataFactoryExec struct {
	exe        string
	prefixArgs []string
	workDir    string
}

func (d dataFactoryExec) valid() bool {
	return strings.TrimSpace(d.exe) != ""
}

func (d dataFactoryExec) displayPath() string {
	if !d.valid() {
		return ""
	}
	if len(d.prefixArgs) == 0 {
		return d.exe
	}
	return d.exe + " " + strings.Join(d.prefixArgs, " ")
}

func (d dataFactoryExec) command(factory commandFactory, args ...string) *exec.Cmd {
	allArgs := append(append([]string{}, d.prefixArgs...), args...)
	cmd := factory(d.exe, allArgs...)
	if d.workDir != "" {
		cmd.Dir = d.workDir
	}
	return cmd
}

// resolveDataFactoryLaunch 按优先级定位 DataFactory 启动方式。
//
//  1. 环境变量 SUPCON_DATAFACTORY_PATH
//  2. 从可执行文件目录向上查找 DataFactory.exe（最多 8 层）
//  3. 仓库根目录下的 DataFactory.exe
//  4. 仓库根目录下的 standalone_main.py + python（开发态 wails dev）
func resolveDataFactoryLaunch() (dataFactoryExec, error) {
	if custom := strings.TrimSpace(os.Getenv(envDataFactoryPath)); custom != "" {
		abs, err := filepath.Abs(custom)
		if err != nil {
			return dataFactoryExec{}, fmt.Errorf("解析 %s 失败: %w", envDataFactoryPath, err)
		}
		if _, err := os.Stat(abs); err != nil {
			return dataFactoryExec{}, fmt.Errorf("%s=%q 不存在", envDataFactoryPath, abs)
		}
		return dataFactoryExec{exe: abs, workDir: filepath.Dir(abs)}, nil
	}

	if launch, ok := findDataFactoryExeFrom(os.Executable); ok {
		return launch, nil
	}

	repoRoot, err := config.ResolveRepoRoot()
	if err == nil {
		exePath := filepath.Join(repoRoot, "DataFactory.exe")
		if _, err := os.Stat(exePath); err == nil {
			abs, _ := filepath.Abs(exePath)
			return dataFactoryExec{exe: abs, workDir: repoRoot}, nil
		}
		if launch, ok := launchFromStandaloneMain(repoRoot); ok {
			return launch, nil
		}
	}

	return dataFactoryExec{}, fmt.Errorf(
		"未设置 DataFactory 路径：未找到 DataFactory.exe 或 %s；可设置 %s 或 %s",
		standaloneEntry,
		envDataFactoryPath,
		"SUPCON_TOOL_REPO_ROOT",
	)
}

func findDataFactoryExeFrom(exeFn func() (string, error)) (dataFactoryExec, bool) {
	exePath, err := exeFn()
	if err != nil {
		return dataFactoryExec{}, false
	}
	dir, err := filepath.Abs(filepath.Dir(exePath))
	if err != nil {
		return dataFactoryExec{}, false
	}
	for i := 0; i < 8; i++ {
		candidate := filepath.Join(dir, "DataFactory.exe")
		if _, err := os.Stat(candidate); err == nil {
			abs, _ := filepath.Abs(candidate)
			return dataFactoryExec{exe: abs, workDir: filepath.Dir(abs)}, true
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return dataFactoryExec{}, false
}

func launchFromStandaloneMain(repoRoot string) (dataFactoryExec, bool) {
	entry := filepath.Join(repoRoot, standaloneEntry)
	if _, err := os.Stat(entry); err != nil {
		return dataFactoryExec{}, false
	}
	python := resolvePythonExecutable()
	if python == "" {
		return dataFactoryExec{}, false
	}
	absEntry, _ := filepath.Abs(entry)
	return dataFactoryExec{
		exe:        python,
		prefixArgs: []string{absEntry},
		workDir:    repoRoot,
	}, true
}

func resolvePythonExecutable() string {
	if custom := strings.TrimSpace(os.Getenv(envPythonPath)); custom != "" {
		return custom
	}
	for _, name := range []string{"python", "python3", "py"} {
		if path, err := exec.LookPath(name); err == nil {
			return path
		}
	}
	return ""
}

type DataFactoryLaunchInfo struct {
	Exe        string
	PrefixArgs []string
	WorkDir    string
}

func ResolveDataFactoryLaunchPublic() (DataFactoryLaunchInfo, error) {
	d, err := resolveDataFactoryLaunch()
	if err != nil {
		return DataFactoryLaunchInfo{}, err
	}
	return DataFactoryLaunchInfo{Exe: d.exe, PrefixArgs: d.prefixArgs, WorkDir: d.workDir}, nil
}
