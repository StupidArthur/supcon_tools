package team

// Machine 是表格中机器列的显示信息。
type Machine struct {
	Zkjs    string `json:"zkjs"`    // 编号，如 "zkjs03"
	CloudID string `json:"cloudId"` // 云电脑ID，如 "D0026080523483810"
}

// Team 是表格的一行数据（前端 DTO 对应）。
type Team struct {
	Seq      int      `json:"seq"`
	Name     string   `json:"name"`
	TenantID string   `json:"tenantId"`
	Username string   `json:"username"`
	Machine  Machine  `json:"machine"`
	IP       string   `json:"ip"`
	Type     string   `json:"type"`
}

// Env 是 config.json 中单个租户的原始结构。
type Env struct {
	Name     string `json:"name"`
	TenantID string `json:"tenant_id"`
	Username string `json:"username"`
	Password string `json:"password"`
	Type     string `json:"type"`
	Zkjs     string `json:"zkjs"`
	CloudID  string `json:"cloud_id"`
	IPv4     string `json:"ipv4"`
}

// Config 是 config.json 的完整结构。
type Config struct {
	BaseURL      string `json:"base_url"`
	Admin        Admin  `json:"admin"`
	Environments []Env  `json:"environments"`
}

// Admin 是全局管理员账号。
type Admin struct {
	Username string `json:"username"`
	Password string `json:"password"`
	TenantID string `json:"tenant_id"`
}
