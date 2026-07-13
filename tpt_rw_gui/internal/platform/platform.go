// Package platform 留作系统能力位(对话框 / 文件夹打开等),本工具暂不需要。
// 占位文件,避免空目录在某些 git/GitHub UI 行为不一致。
package platform

import "errors"

// ErrNotImplemented 留给将来真正接入对话框/文件路径时实现。
var ErrNotImplemented = errors.New("platform: not implemented yet")
