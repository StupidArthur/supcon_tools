// Package app 是 tpt_rw_gui 的组合根。依赖在这里构造,业务包不允许反向 import。
package app

import (
	"github.com/yzc/tpt_api"

	"tpt_rw_gui/internal/bindings"
	"tpt_rw_gui/internal/rw"
	"tpt_rw_gui/internal/session"
)

// Container 持有所有 binding、生命周期、共享 *tptapi.Service。
type Container struct {
	Lifecycle      *Lifecycle
	SessionBinding *bindings.SessionBinding
	RWBinding      *bindings.RWBinding
}

// NewContainer 构造完整依赖图。失败直接返。
//
// 注意:tptapi.Service 同时被 session + rw 共享,登录态只此一份。
func NewContainer() (*Container, error) {
	tptSvc := tptapi.NewService()

	sessSvc := session.NewService(tptSvc)
	port := rw.NewTptClientAdapter(tptSvc)
	rwSvc := rw.NewService(port)

	return &Container{
		Lifecycle:      NewLifecycle(),
		SessionBinding: bindings.NewSessionBinding(sessSvc),
		RWBinding:      bindings.NewRWBinding(sessSvc, rwSvc),
	}, nil
}

// Wire 把 binding 注册为 lifecycle 的 ContextReceiver,使 Startup 能把根 ctx 推给它们。
// 必须在 wails.Run 之前调用(由 main.go 调用)。
func (c *Container) Wire() {
	c.Lifecycle.Register(c.SessionBinding)
	c.Lifecycle.Register(c.RWBinding)
}
