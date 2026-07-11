// util.go - binding 层公共工具。
package bindings

import "fmt"

// RecoverPanic 在 defer 中调用,捕获 panic 转 error(配合命名返回值 err)。
// 替代原 App.recoverErr:错误经 (T, error) 返回,前端 Promise reject。
func RecoverPanic(err *error) {
	if r := recover(); r != nil {
		*err = fmt.Errorf("panic: %v", r)
	}
}
