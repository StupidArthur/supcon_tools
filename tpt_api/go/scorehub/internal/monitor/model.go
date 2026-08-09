package monitor

// TagNames 是中控杯约定的 39 个位号：原 33 个 + 策略新增 6 个
// （TE60501.PV / TE60411.PV / TE60409.PV / LIC_60402.PV/SV/MV）。
var TagNames = []string{
	"PRAC_LOAD.VALUE", "EXAM_LOAD.VALUE", "LOAD_RSP.VALUE",
	"FICQ_60101.PV", "FICQ_60101.SV", "FICQ_60101.MV",
	"FICQ_60401.PV", "FICQ_60401.SV", "FICQ_60401.MV",
	"FICQ_60402.PV", "FICQ_60402.SV", "FICQ_60402.MV",
	"LIC_60501.PV", "LIC_60501.SV", "LIC_60501.MV",
	"PICA_60402.PV", "PICA_60402.SV", "PICA_60402.MV",
	"FT60201.PV", "FT60501.PV", "LT60401.PV",
	"TE60401.PV", "TE60402.PV", "TE60403.PV", "TE60404.PV", "TE60405.PV",
	"TE60406.PV", "TE60407.PV", "TE60408.PV", "TE60410.PV",
	"T602D.VALUE", "T602RR.VALUE", "T604D.PV",
	"TE60501.PV", "TE60411.PV", "TE60409.PV",
	"LIC_60402.PV", "LIC_60402.SV", "LIC_60402.MV",
}

// QualityGood 是位号质量码 GOOD（与 OPC UA Good=192 对齐）。
const QualityGood = 192

// SampleTagName 是用于展示"数据在变化"的采样位号：选一个长时间非 0 的流量位号。
const SampleTagName = "FT60201.PV"

// Report 是单个租户的数据源监控结果。
type Report struct {
	Name     string   `json:"name"`
	TenantID string   `json:"tenantId"`
	DsName   string   `json:"dsName"`
	DsTarUrl string   `json:"dsTarUrl"`
	DsFound  bool     `json:"dsFound"`
	DsAlive  bool     `json:"dsAlive"`
	TagTotal int      `json:"tagTotal"`
	TagGood  int      `json:"tagGood"`
	BadTags  []string `json:"badTags"`
	Error    string   `json:"error"`

	SampleValue string `json:"sampleValue"` // 采样位号当前值
	SampleTime  string `json:"sampleTime"`  // 采样位号 timeStamp 转成的时间字符串
}

// IsAbnormal 报告本周期是否异常：
// 数据源须找到且在线，位号须全部 GOOD，且无错误消息。
func (r *Report) IsAbnormal() bool {
	if r.Error != "" || !r.DsFound || !r.DsAlive {
		return true
	}
	if r.TagTotal != len(TagNames) || r.TagGood != len(TagNames) {
		return true
	}
	return false
}

// Cycle 是一整轮轮询的快照（当前所有租户的结果）。
type Cycle struct {
	At      string   `json:"at"` // RFC3339 时间
	DurMs   int64    `json:"durMs"`
	Skipped bool     `json:"skipped"`
	Reports []Report `json:"reports"`
}

// HasAbnormal 本轮是否存在任一异常租户。
func (c *Cycle) HasAbnormal() bool {
	for i := range c.Reports {
		if c.Reports[i].IsAbnormal() {
			return true
		}
	}
	return false
}

// AbnormalReports 返回本轮全部异常租户的报告。
func (c *Cycle) AbnormalReports() []Report {
	var out []Report
	for i := range c.Reports {
		if c.Reports[i].IsAbnormal() {
			out = append(out, c.Reports[i])
		}
	}
	return out
}

// AbnormalEntry 是单个租户最近一次异常的记录（相同租户只保留最新一条）。
type AbnormalEntry struct {
	At     string `json:"at"`     // 该次异常所在周期的时间
	Report Report `json:"report"`
}

// Snapshot 是推送给前端的整体状态：最新一轮 + 每租户最近一次异常（按租户去重，最新在前）。
type Snapshot struct {
	Cycle    Cycle           `json:"cycle"`
	Abnormal []AbnormalEntry `json:"abnormal"`
}
