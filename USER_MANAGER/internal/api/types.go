// Package api 提供 TPT 后台用户管理域的 HTTP 客户端。
//
// 设计原则（见 USER_MANAGER/doc/design.md）：
//   - 与父级 alg_update/api.py (Python) 一一对应，端点 URL、请求/响应字段、错误码语义对齐
//   - 不依赖 Wails，可独立 go test
//   - 通过 Client 暴露的方法让 Wails 绑定层 (app.go) 复用
package api

// User 是 listByOrgId 返回的单条记录，对应 /xpt-system/api/system-manager/umsAdmin/listByOrgId 的 records[] 元素。
type User struct {
	ID         int64  `json:"id"`
	Username   string `json:"username"`
	Code       string `json:"code"`
	NickName   string `json:"nickName"`
	Email      string `json:"email"`
	Phone      string `json:"phone"`
	Gender     int    `json:"gender"`
	Status     int    `json:"status"`
	Type       int    `json:"type"`
	TenantID   string `json:"tenantId"`
	DelFlag    int    `json:"delFlag"`
	CreateTime string `json:"createTime"`
	LoginTime  string `json:"loginTime"`
	UpdateTime string `json:"updateTime"`
}

// UserDraft 是 create 时的输入载荷（单条 / 批量均用此类型）。
// orgIds / roleIds 在 v1 不暴露给前端，写死 [1] / "5"。
type UserDraft struct {
	Username string `json:"username"` // 必填，登录账号
	Password string `json:"password"` // 必填，明文（平台 UMS 不做 hash）
	NickName string `json:"nickName"` // 必填，昵称 / 显示名
	Email    string `json:"email"`    // 可选
	Phone    string `json:"phone"`    // 可选
}

// PageResponse 是 list 接口的 MyBatis Page 结构。
type PageResponse struct {
	Records []User `json:"records"`
	Total   int64  `json:"total"`
	Size    int    `json:"size"`
	Current int    `json:"current"`
	Pages   int    `json:"pages"`
	Orders  []any  `json:"orders"`
}

// LoginResponse 是登录接口 content 字段的形态。
type LoginResponse struct {
	Token string `json:"token"`
}

// OperationStatus 是 create / resetPwd 等写操作的状态返回（无 content）。
type OperationStatus struct {
	Code string `json:"code"` // 业务 code，00000 = 成功
	Msg  string `json:"msg"`
}

// LoginConfig 持久化用的 URL + 租户 ID（不存密码）。
type LoginConfig struct {
	URL      string `json:"url"`
	TenantID string `json:"tenantId"`
}
