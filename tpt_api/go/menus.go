package tptapi

import (
	"context"
	"net/http"
)

// TPT admin 菜单管理端点。
//
// POST /tpt-admin/system-manager/umsMenu  创建/更新菜单项
// 同一端点承载两种业务：
//   1. 创建目录菜单（type=0）：如"数据仓库"挂在"系统管理"下，不带路由
//   2. 创建页面菜单（type=1, pathType=3）：如"批流任务模板"挂在"数据仓库"下，带内路由路径

const (
	// MenuCreatePath 创建/更新菜单端点
	MenuCreatePath = "/tpt-admin/system-manager/umsMenu"
	// RoleAllocMenuPath 给角色分配菜单端点
	RoleAllocMenuPath = "/xpt-system/api/system-manager/umsRole/allocMenu"
)

// NormalRoleId 普通用户角色 ID（平台默认）。
const NormalRoleId = 5

// MenuDraft 是创建菜单的输入载荷。
//
// 字段含义：
//   - parentID:   父菜单 ID（顶级为 0）
//   - parentName: 父菜单标题（顶级为空串）
//   - title:      菜单标题
//   - level:      层级（0=顶级, 1=二级, ...）
//   - type:       类型（0=目录, 1=页面, 2=按钮）
//   - sort:       排序序号
//   - status:     状态（0=启用, 1=禁用）
//   - icon:       图标 class（如 "fa-connectdevelop"）
//   - name:       路由路径（目录类型可空）
//   - pathType:   路径类型（0=无, 2=外链, 3=内路由）
//   - dataType:   数据类型（0=系统菜单, 1=业务菜单）
type MenuDraft struct {
	ParentID   int    `json:"parentId"`
	ParentName string `json:"parentName"`
	Title      string `json:"title"`
	Level      int    `json:"level"`
	Type       int    `json:"type"`
	Sort       int    `json:"sort"`
	Status     int    `json:"status"`
	Icon       string `json:"icon"`
	Name       string `json:"name,omitempty"`
	PathType   int    `json:"pathType,omitempty"`
	DataType   int    `json:"dataType,omitempty"`
}

// CreateMenu 创建一个菜单项（通用，直接传 MenuDraft）。
//
// POST /tpt-admin/system-manager/umsMenu
// body: {"data": {parentId, level, status, parentName, type, title, sort, icon, ...}}
func (c *Client) CreateMenu(ctx context.Context, draft MenuDraft) (map[string]any, error) {
	body := map[string]any{
		"data": map[string]any{
			"parentId":   draft.ParentID,
			"level":      draft.Level,
			"status":     draft.Status,
			"parentName": draft.ParentName,
			"type":       draft.Type,
			"title":      draft.Title,
			"sort":       draft.Sort,
			"icon":       draft.Icon,
		},
	}
	// Name / PathType / DataType 仅在非空/非零时附加
	inner := body["data"].(map[string]any)
	if draft.Name != "" {
		inner["name"] = draft.Name
	}
	if draft.PathType != 0 {
		inner["pathType"] = draft.PathType
	}
	if draft.DataType != 0 {
		inner["dataType"] = draft.DataType
	}

	var out map[string]any
	if err := c.doRequest(ctx, http.MethodPost, MenuCreatePath, body, &out, false); err != nil {
		return nil, err
	}
	if out == nil {
		out = map[string]any{"id": nil}
	}
	return out, nil
}

// CreateDirMenu 创建目录菜单（type=0）。
//
// 业务场景：在父菜单下新建一个目录分类，如"数据仓库"挂在"系统管理"下。
// 不带路由路径，纯分组节点。
func (c *Client) CreateDirMenu(ctx context.Context, parentID int, parentName, title string,
	level, sort int, icon string) (map[string]any, error) {
	if icon == "" {
		icon = "fa-connectdevelop"
	}
	draft := MenuDraft{
		ParentID:   parentID,
		ParentName: parentName,
		Title:      title,
		Level:      level,
		Type:       0,
		Sort:       sort,
		Status:     0,
		Icon:       icon,
	}
	return c.CreateMenu(ctx, draft)
}

// CreatePageMenu 创建页面菜单（type=1）。
//
// pathType:
//   - 3 = 内路由（如 /ware-house/filemanage）
//   - 2 = 外链（如 /tpt-admin）
//
// 业务场景：
//   - 内路由：在目录菜单下新建页面，如"文件管理"挂在"数据仓库"下
//   - 外链：在顶级菜单下新建后台管理入口，如"后台管理"挂在"TptSceneApp"下
func (c *Client) CreatePageMenu(ctx context.Context, parentID int, parentName, title, route string,
	level, sort int, icon string, pathType int) (map[string]any, error) {
	if icon == "" {
		icon = "fa-connectdevelop"
	}
	draft := MenuDraft{
		ParentID:   parentID,
		ParentName: parentName,
		Title:      title,
		Level:      level,
		Type:       1,
		Sort:       sort,
		Status:     0,
		Icon:       icon,
		Name:       route,
		PathType:   pathType,
	}
	return c.CreateMenu(ctx, draft)
}

// UpdateMenuStatus 修改菜单状态（启用/禁用）。
//
// PUT /tpt-admin/system-manager/umsMenu
// body: {"data": {"id": menuID, "status": status}}
//
//   - status: 0=启用, 1=禁用（隐藏）
func (c *Client) UpdateMenuStatus(ctx context.Context, menuID, status int) (map[string]any, error) {
	body := map[string]any{
		"data": map[string]any{
			"id":     menuID,
			"status": status,
		},
	}
	var out map[string]any
	if err := c.doRequest(ctx, http.MethodPut, MenuCreatePath, body, &out, false); err != nil {
		return nil, err
	}
	return out, nil
}

// DisableMenu 禁用菜单（status=1，隐藏不展示）。
func (c *Client) DisableMenu(ctx context.Context, menuID int) (map[string]any, error) {
	return c.UpdateMenuStatus(ctx, menuID, 1)
}

// EnableMenu 启用菜单（status=0，正常展示）。
func (c *Client) EnableMenu(ctx context.Context, menuID int) (map[string]any, error) {
	return c.UpdateMenuStatus(ctx, menuID, 0)
}

// AllocRoleMenus 给角色分配菜单权限。
//
// POST /xpt-system/api/system-manager/umsRole/allocMenu
// body: {"data": {"id": roleID, "menuIdList": [...]}}
//
// 注意：
//   - 此接口响应较慢，建议 client 实例 timeout 设大（如 60s）
//   - menuIdList 平台侧 int/str 混用，保持原样传入即可
//   - roleID=5 为"普通用户角色"（平台默认）
//
// 业务场景：创建完所有菜单后，将菜单权限分配给普通用户角色，
// 使该租户下的普通用户能看到"系统管理"和"TptSceneApp"下的指定菜单。
func (c *Client) AllocRoleMenus(ctx context.Context, roleID int, menuIDs []any) (map[string]any, error) {
	body := map[string]any{
		"data": map[string]any{
			"id":         roleID,
			"menuIdList": menuIDs,
		},
	}
	var out map[string]any
	if err := c.doRequest(ctx, http.MethodPost, RoleAllocMenuPath, body, &out, false); err != nil {
		return nil, err
	}
	return out, nil
}
