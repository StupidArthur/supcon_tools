package bindings

import (
	"fmt"
	"os"
	"os/exec"
)

// MakeLongRunningCommandForTest 是 makeLongRunningCommand 的 exported 包装，
// 给 app/lifecycle_test 等外部包使用。返回的命令会让 helper 进程睡眠指定秒数。
func MakeLongRunningCommandForTest(sleepSeconds int) commandFactory {
	return func(name string, arg ...string) *exec.Cmd {
		cs := []string{"-test.run=TestHelperProcess", "--", name}
		cs = append(cs, arg...)
		cmd := exec.Command(os.Args[0], cs...)
		cmd.Env = []string{
			"GO_WANT_HELPER_PROCESS=1",
			"HELPER_EXIT_CODE=0",
			fmt.Sprintf("HELPER_SLEEP=%d", sleepSeconds),
		}
		return cmd
	}
}
