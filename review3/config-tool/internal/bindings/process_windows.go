//go:build windows

package bindings

import (
	"os/exec"
	"syscall"
)

// configureBackgroundProcess 在 Windows 上配置后台进程（todo.md §5.5）。
//
// 要求：
//   - 如果 cmd.SysProcAttr == nil，再创建
//   - 设置 HideWindow = true
//   - 使用位或合并 CREATE_NO_WINDOW (0x08000000)
//   - 不覆盖已有 CreationFlags
//   - 不覆盖其他 SysProcAttr 字段
func configureBackgroundProcess(cmd *exec.Cmd) {
	if cmd.SysProcAttr == nil {
		cmd.SysProcAttr = &syscall.SysProcAttr{}
	}
	cmd.SysProcAttr.HideWindow = true
	cmd.SysProcAttr.CreationFlags |= 0x08000000 // CREATE_NO_WINDOW
}
