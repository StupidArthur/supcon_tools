//go:build windows

package main

import (
	"os"

	"golang.org/x/sys/windows"
)

// redirectStderr 在 Windows GUI 程序下通过 SetStdHandle 真正重定向 stderr，
// 使 Go runtime panic / OOM 等写入 crash.log。
func redirectStderr(f *os.File) {
	os.Stderr = f
	windows.SetStdHandle(windows.STD_ERROR_HANDLE, windows.Handle(f.Fd()))
}
