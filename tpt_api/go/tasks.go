package tptapi

import (
	"context"
	"encoding/json"
)

// ibd-schedule 任务管理接口（TPT 后台任务调度）。
//
// 端点：POST /ibd-schedule-web/api/task/page 分页拉任务列表
// 响应为 TPT 标准格式 {code:"00000", content:{records, total, ...}}。

// ScheduleTaskPath 任务分页查询端点。
const ScheduleTaskPath = "/ibd-schedule-web/api/task/page"

// ScheduleTask 是 /task/page 返回的单条任务记录。
type ScheduleTask struct {
	ID                 string `json:"id"`
	JobType            int    `json:"jobType"`
	FixRate            int    `json:"fixRate"`
	CronExpression     string `json:"cronExpression"`
	EnDescription      string `json:"enDescription"`
	Description        string `json:"description"`
	JobStatus          int    `json:"jobStatus"`
	JobName            string `json:"jobName"`
	ScheduleParam      string `json:"scheduleParam"`
	ScheduleParamName  string `json:"scheduleParamName"`
	InParameterValues  string `json:"inParameterValues"`
	ScheduleType       int    `json:"scheduleType"`
	FileName           string `json:"fileName"`
	UploadPath         string `json:"uploadPath"`
	Frequency          int    `json:"frequency"`
	MonitorTaskID      string `json:"monitorTaskId"`
	InitialStartupTime string `json:"initialStartupTime"`
	CreateBy           int64  `json:"createBy"`
	UpdateBy           int64  `json:"updateBy"`
	CreateUser         string `json:"createUser"`
	UpdateUser         string `json:"updateUser"`
	CreateTime         string `json:"createTime"`
	UpdateTime         string `json:"updateTime"`
}

// ScheduleTaskPage 是 /task/page 的 MyBatis 分页结构。
type ScheduleTaskPage struct {
	Records []ScheduleTask `json:"records"`
	Total   int64          `json:"total"`
	Size    int            `json:"size"`
	Current int            `json:"current"`
	Pages   int            `json:"pages"`
}

// ListScheduleTasks 分页查询调度任务（POST /ibd-schedule-web/api/task/page）。
//
//   - page 从 1 开始；pageSize 默认 10
//   - createTimeBegin / createTimeEnd 为 "yyyy-MM-dd HH:mm:ss"，空串表示不过滤
func (c *TptClient) ListScheduleTasks(ctx context.Context, page, pageSize int, createTimeBegin, createTimeEnd string) (*ScheduleTaskPage, error) {
	if page < 1 {
		page = 1
	}
	if pageSize < 1 {
		pageSize = 10
	}
	body := map[string]any{
		"data": map[string]any{
			"createTime_begin": createTimeBegin,
			"createTime_end":   createTimeEnd,
		},
		"requestBase": pageBaseSorted(page, pageSize, ""),
	}
	content, err := c.request("POST", ScheduleTaskPath, body, false)
	if err != nil {
		return nil, err
	}
	var out ScheduleTaskPage
	if err := json.Unmarshal(content, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// GetAllScheduleTasks 自动翻页拉取全部调度任务。
func (c *TptClient) GetAllScheduleTasks(ctx context.Context, pageSize int) ([]ScheduleTask, error) {
	if pageSize < 1 {
		pageSize = 200
	}
	var all []ScheduleTask
	page := 1
	for {
		resp, err := c.ListScheduleTasks(ctx, page, pageSize, "", "")
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
