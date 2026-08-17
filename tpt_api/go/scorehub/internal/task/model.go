package task

// TeamTaskStats 是单个选手租户的任务汇总（前端 DTO）。
type TeamTaskStats struct {
	Seq      int    `json:"seq"`
	Name     string `json:"name"`
	TenantID string `json:"tenantId"`
	Total    int    `json:"total"`
	Enabled  int    `json:"enabled"`
	// EnabledDetail 是启用中任务的周期明细，横向用 | 分隔，
	// 每项为 cron 表达式或 "fix:秒"（无 cron 时用 fixRate）。
	EnabledDetail string `json:"enabledDetail"`
}
