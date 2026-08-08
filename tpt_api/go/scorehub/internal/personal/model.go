package personal

// Row 是个性化管理表格的一行（前端 DTO 对应）。
type Row struct {
	Seq        int      `json:"seq"`
	Name       string   `json:"name"`
	TenantID   string   `json:"tenantId"`
	Username   string   `json:"username"`
	TotalScore *float64 `json:"totalScore"`
}

// ScoreRecord 是控制成绩记录（tenant-detail 的 data.scoreRecords 项）。
type ScoreRecord struct {
	ID            string   `json:"id"`
	Score         *float64 `json:"score"`
	Sci           *float64 `json:"sci"`
	Se            *float64 `json:"se"`
	Ssafe         *float64 `json:"ssafe"`
	Ssmi          *float64 `json:"ssmi"`
	Status        int      `json:"status"`
	AlgorithmType string   `json:"algorithmType"`
	StartWorktime string   `json:"startWorktime"`
	EndWorktime   string   `json:"endWorktime"`
	IsBest        bool     `json:"isBest"`
}

// FileRecord 是软测量上传文件记录（tenant-detail 的 data.files 项）。
type FileRecord struct {
	ID         string   `json:"id"`
	FileName   string   `json:"fileName"`
	UploadTime string   `json:"uploadTime"`
	Score      *float64 `json:"score"`
}

// Detail 是单个租户的成绩详情（详情弹窗数据）。
type Detail struct {
	TenantID     string        `json:"tenantId"`
	ScoreRecords []ScoreRecord `json:"scoreRecords"`
	Files        []FileRecord  `json:"files"`
}

// CleanupResult 是清空操作结果。
type CleanupResult struct {
	Success bool           `json:"success"`
	Counts  map[string]int `json:"counts"`
	Error   string         `json:"error"`
}
