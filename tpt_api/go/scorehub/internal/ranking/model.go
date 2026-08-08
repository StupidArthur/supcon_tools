package ranking

// Item 是排行榜表格的一行（前端 DTO 对应）。
type Item struct {
	Rank            int      `json:"rank"`
	TenantID        string   `json:"tenantId"`
	Name            string   `json:"name"`
	ControlScore    *float64 `json:"controlScore"`
	SoftSensorScore *float64 `json:"softSensorScore"`
	TotalScore      float64  `json:"totalScore"`
}
