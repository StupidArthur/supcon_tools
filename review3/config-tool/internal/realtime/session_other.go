//go:build !windows

package realtime

// windowsProcessAlive 在非 Windows 平台不会被调用；
// 保留空实现以满足编译器。
func windowsProcessAlive(pid int) bool {
	return false
}
