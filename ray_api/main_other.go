//go:build !windows

package main

import "os"

// redirectStderr 非 Windows 平台只做 os.Stderr 赋值。
func redirectStderr(f *os.File) {
	os.Stderr = f
}
