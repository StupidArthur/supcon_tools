//go:build !windows

package bindings

import "os/exec"

// configureBackgroundProcess 在非 Windows 平台为 no-op（todo.md §5.5）。
func configureBackgroundProcess(cmd *exec.Cmd) {
	// 非 Windows 平台不需要隐藏窗口
}
