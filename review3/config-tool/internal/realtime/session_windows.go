//go:build windows

package realtime

import (
	"syscall"
	"unsafe"
)

// windowsProcessAlive 通过 OpenProcess + GetExitCodeProcess 检查进程是否仍 alive。
//   - STILL_ACTIVE = 259 视为 alive
//   - 句柄无法打开（ERROR_INVALID_PARAMETER / ERROR_ACCESS_DENIED）：视为死亡
//
// 任何错误一律视为死亡，不抛错。
func windowsProcessAlive(pid int) bool {
	const (
		processQueryLimitedInformation = 0x1000
		stillActive                    = 259
	)
	handle, err := syscall.OpenProcess(processQueryLimitedInformation, false, uint32(pid))
	if err != nil {
		return false
	}
	defer syscall.CloseHandle(handle)

	var exitCode uint32
	ret, _, _ := procGetExitCodeProcess.Call(
		uintptr(handle),
		uintptr(unsafe.Pointer(&exitCode)),
	)
	if ret == 0 {
		return false
	}
	return exitCode == stillActive
}

var (
	modkernel32                  = syscall.NewLazyDLL("kernel32.dll")
	procGetExitCodeProcess       = modkernel32.NewProc("GetExitCodeProcess")
)
