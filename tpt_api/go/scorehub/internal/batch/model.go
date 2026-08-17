package batch

import "fmt"

// EvalConfig 是全局评估配置（服务端单行，id=1），作用于所有租户。
type EvalConfig struct {
	ID                         int    `json:"id"`
	PracLoadEnabled            int    `json:"pracLoadEnabled"`
	ExamLoadEnabled            int    `json:"examLoadEnabled"`
	EvalDurationMinutes        int    `json:"evalDurationMinutes"`
	StartWorktimeDelayMinutes  int    `json:"startWorktimeDelayMinutes"`
	AddTime                    string `json:"addTime"`
	UpdateTime                 string `json:"updateTime"`
}

// UpdateResult 是更新评估配置的结果。
type UpdateResult struct {
	Success bool   `json:"success"`
	Error   string `json:"error"`
}

// TenantClearResult 是清空单个租户评分记录的结果。
type TenantClearResult struct {
	Seq      int    `json:"seq"`
	Name     string `json:"name"`
	TenantID string `json:"tenantId"`
	Success  bool   `json:"success"`
	Error    string `json:"error"`
}

// ClearAllResult 是批量清空所有选手租户评分记录的汇总结果。
type ClearAllResult struct {
	Success int                 `json:"success"`
	Failed  int                 `json:"failed"`
	Items   []TenantClearResult `json:"items"`
}

// ClearError 是清空接口业务失败（code != 200）。
type ClearError struct {
	Code    any
	Message string
}

func (e *ClearError) Error() string {
	return "clear scores failed: code=" + fmt.Sprint(e.Code) + " message=" + e.Message
}
