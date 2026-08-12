package monitor

// TagNames 是中控杯约定的 42 个位号：原 33 个 + 策略新增 6 个 + 最新新增 3 个
// （FICQ_60201.PV / LT60402.PV / LT60501.PV）。
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
	"FICQ_60201.PV", "LT60402.PV", "LT60501.PV",
}

// QualityGood 是位号质量码 GOOD（与 OPC UA Good=192 对齐）。
const QualityGood = 192

// SampleTagName 是用于展示"数据在变化"的采样位号：选一个长时间非 0 的流量位号。
const SampleTagName = "FICQ_60401.MV"

// 异常类型常量（子异常）。
const (
	AbnNone       = 0
	AbnAPIFailure = 1 // API 调用失败（连续 2 轮）
	AbnDsNotFound = 2 // 未找到数据源
	AbnDsOffline  = 3 // 数据源离线
	AbnTagBad     = 4 // 位号质量 BAD
	AbnValueStale = 5 // 采样位号值停滞（连续 2 轮未变）
)

// AbnLabels 异常类型中文名。
var AbnLabels = map[int]string{
	AbnAPIFailure: "API异常",
	AbnDsNotFound: "数据源缺失",
	AbnDsOffline:  "数据源离线",
	AbnTagBad:     "位号异常",
	AbnValueStale: "值停滞",
}

// SubAbnormal 是单个子异常的状态。
type SubAbnormal struct {
	Active bool   `json:"active"`
	Since  string `json:"since"`  // 异常产生时间 RFC3339
	Detail string `json:"detail"` // 异常详情
}

// Report 是单个租户的数据源监控结果 + 异常状态。
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

	SampleValue string `json:"sampleValue"`
	SampleTime  string `json:"sampleTime"`

	// 5 个子异常状态
	SubAPIFailure SubAbnormal `json:"subAPIFailure"`
	SubDsNotFound SubAbnormal `json:"subDsNotFound"`
	SubDsOffline  SubAbnormal `json:"subDsOffline"`
	SubTagBad     SubAbnormal `json:"subTagBad"`
	SubValueStale SubAbnormal `json:"subValueStale"`

	// 总异常：任一子异常活跃
	Abnormal bool `json:"abnormal"`

	// 上一次异常（所有子异常消失后保留）
	LastAbnType      int    `json:"lastAbnType"`
	LastAbnSince     string `json:"lastAbnSince"`
	LastAbnDetail    string `json:"lastAbnDetail"`
	LastAbnConfirmed bool   `json:"lastAbnConfirmed"`
}

// Cycle 是一整轮轮询的快照（当前所有租户的结果）。
type Cycle struct {
	At      string   `json:"at"`
	DurMs   int64    `json:"durMs"`
	Skipped bool     `json:"skipped"`
	Reports []Report `json:"reports"`
}

// Snapshot 是推送给前端的整体状态。
type Snapshot struct {
	Cycle Cycle `json:"cycle"`
}
