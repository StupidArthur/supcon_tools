package batch

// EvalConfig 是全局评估配置（服务端单行，id=1），作用于所有租户。
type EvalConfig struct {
	ID                  int    `json:"id"`
	PracLoadEnabled     int    `json:"pracLoadEnabled"`
	ExamLoadEnabled     int    `json:"examLoadEnabled"`
	EvalDurationMinutes int    `json:"evalDurationMinutes"`
	AddTime             string `json:"addTime"`
	UpdateTime          string `json:"updateTime"`
}

// UpdateResult 是更新评估配置的结果。
type UpdateResult struct {
	Success bool   `json:"success"`
	Error   string `json:"error"`
}
