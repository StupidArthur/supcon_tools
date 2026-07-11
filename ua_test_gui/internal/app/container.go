// container.go - 组合根:装配所有依赖,暴露 bindings 给 main。
//
// 唯一组合根:所有 new() 集中在此,业务包只定义构造函数,不互相 new。
// 依赖方向:app -> bindings + adapters + features。
package app

import (
	"log/slog"

	"ua_test_gui/internal/adapters/opcua"
	"ua_test_gui/internal/adapters/pyworker"
	"ua_test_gui/internal/adapters/sqlite"
	"ua_test_gui/internal/bindings"
	"ua_test_gui/internal/env"
	"ua_test_gui/internal/mock"
	"ua_test_gui/internal/provision"
	"ua_test_gui/internal/subject"
	"ua_test_gui/internal/verify"
)

// Container 组合根,持有 6 个 binding + 需要生命周期管理的内部组件。
type Container struct {
	Subject   *bindings.SubjectBinding
	Env       *bindings.EnvBinding
	Mock      *bindings.MockBinding
	Provision *bindings.ProvisionBinding
	Verify    *bindings.VerifyBinding
	History   *bindings.HistoryBinding

	store   *sqlite.Store
	mockMgr *pyworker.MockManager
}

// NewContainer 装配所有依赖。
func NewContainer() *Container {
	cfg := DefaultConfig()

	store, err := sqlite.OpenStore(cfg.DBPath)
	if err != nil {
		slog.Error("打开数据库失败", "err", err, "path", cfg.DBPath)
		// store 为 nil,service 容错(store==nil 时不落库)
	}

	// store==nil 时传 nil 接口(避免 Go 接口 nil 陷阱:typed nil != nil)
	var resultStore verify.ResultStore
	if store != nil {
		resultStore = store
	}

	mockMgr := pyworker.NewMockManager(cfg.MockWorkDir, nil) // notifier 由 Startup 注入

	subjSvc := subject.NewService()
	envSvc := env.NewService(subjSvc)
	mockSvc := mock.NewService(mockMgr, mockMgr) // Runtime + ConfigProvider 均由 MockManager 实现
	provSvc := provision.NewService(subjSvc)
	verSvc := verify.NewService(subjSvc, resultStore, opcua.Factory{})

	return &Container{
		Subject:   bindings.NewSubjectBinding(subjSvc),
		Env:       bindings.NewEnvBinding(envSvc, mockSvc),
		Mock:      bindings.NewMockBinding(mockSvc),
		Provision: bindings.NewProvisionBinding(provSvc),
		Verify:    bindings.NewVerifyBinding(verSvc),
		History:   bindings.NewHistoryBinding(verSvc),
		store:     store,
		mockMgr:   mockMgr,
	}
}
