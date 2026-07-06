package api

import (
	"context"
	"fmt"
	"net/url"
)

// 写操作端点前缀。
const (
	listByOrgPath = "/xpt-system/api/system-manager/umsAdmin/listByOrgId"
	createPath    = "/xpt-system/api/system-manager/umsAdmin"
	resetPwdPath  = "/xpt-system/api/system-manager/umsAdmin/resetPwd"
)

// ListUsers 分页拉后台用户列表。
//   - page 从 1 开始
//   - pageSize 默认 10
//   - orgID 空串表示全部组织
//   - keyword 空串表示不过滤；非空时跨 nickname/username/phone/email 任一字段模糊匹配
//   - searchFields 自定义模糊字段，默认 4 个常见字段
func (c *Client) ListUsers(ctx context.Context, page, pageSize int, orgID, keyword, sort string, searchFields ...string) (*PageResponse, error) {
	if page < 1 {
		page = 1
	}
	if pageSize < 1 {
		pageSize = 10
	}
	if len(searchFields) == 0 {
		searchFields = []string{"nickName", "username", "phone", "email"}
	}
	fieldKeys := ""
	for i, f := range searchFields {
		if i > 0 {
			fieldKeys += "|"
		}
		fieldKeys += "*" + f + "*"
	}
	adminWhere := map[string]string{}
	if keyword != "" {
		adminWhere[fieldKeys] = keyword
	}

	body := map[string]any{
		"data": map[string]any{
			"adminWhere": adminWhere,
			"orgId":      orgID,
		},
		"requestBase": map[string]any{
			"page": fmt.Sprintf("%d-%d", page, pageSize),
			"sort": sort,
		},
	}

	var out PageResponse
	if err := c.doRequest(ctx, listByOrgPath, body, &out, true); err != nil {
		return nil, err
	}
	return &out, nil
}

// GetAllUsers 自动翻页拉全部后台用户。
// 返回所有 users（不去重，不去重 caller 负责）。
func (c *Client) GetAllUsers(ctx context.Context, keyword, sort string, pageSize int, searchFields ...string) ([]User, error) {
	if pageSize < 1 {
		pageSize = 200
	}
	var all []User
	page := 1
	for {
		resp, err := c.ListUsers(ctx, page, pageSize, "", keyword, sort, searchFields...)
		if err != nil {
			return all, err
		}
		all = append(all, resp.Records...)
		if len(resp.Records) < pageSize {
			break
		}
		page++
	}
	return all, nil
}

// CreateUser 创建一个后台用户（POST /xpt-system/api/system-manager/umsAdmin）。
// 响应不含 userId，调用方需 GetAllUsers 反查 username 拿 id。
//
// 内部固定参数（v1 不暴露给前端）：
//   - status: 0
//   - orgIds: [1]
//   - orgName: "默认组织"
//   - type: "2" (普通用户)
//   - roleIds: "5"
//   - gender: "1"
//   - code: 沿用 username
//   - icon: ""
func (c *Client) CreateUser(ctx context.Context, draft UserDraft) (*OperationStatus, error) {
	body := map[string]any{
		"data": map[string]any{
			"status":   0,
			"orgIds":   []int{1},
			"username": draft.Username,
			"code":     draft.Username,
			"nickName": draft.NickName,
			"password": draft.Password,
			"gender":   "1",
			"email":    draft.Email,
			"phone":    draft.Phone,
			"orgName":  "默认组织",
			"type":     "2",
			"roleIds":  "5",
			"icon":     "",
		},
	}

	var out OperationStatus
	if err := c.doRequest(ctx, createPath, body, &out, false); err != nil {
		return nil, err
	}
	return &out, nil
}

// ResetPassword 重置指定用户的密码（POST /xpt-system/api/system-manager/umsAdmin/resetPwd）。
// userID 来自 listByOrgId 返回的 id 字段。
//
// 注意：平台行为是 reset 后旧密码仍可登录（参见 [[tpt-password-history-quirk]]），
// 重置成功 ≠ 旧密码失效。
func (c *Client) ResetPassword(ctx context.Context, userID int64, newPassword string) (*OperationStatus, error) {
	body := map[string]any{
		"data": map[string]any{
			"id":         userID,
			"newPwd":     newPassword,
			"confirmPwd": newPassword,
		},
	}

	var out OperationStatus
	if err := c.doRequest(ctx, resetPwdPath, body, &out, false); err != nil {
		return nil, err
	}
	return &out, nil
}

// _ 占位避免 url 包未使用（保留供后续扩展，例如分页 URL 化场景）
var _ = url.QueryEscape
