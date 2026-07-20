package config

import (
	"time"

	"gopkg.in/yaml.v3"
)

// ValidationIssue 描述模板配置中的一条校验问题。
// Level = "error" 时阻止保存；Level = "warning" 时仅用于 UI 提示。
type ValidationIssue struct {
	Path    string `json:"path"`
	Level   string `json:"level"`
	Message string `json:"message"`
}

// TemplateDocument 是一次无损加载的结果。
// 模板保存只针对此对象中的 Config 字段做白名单修改，原始 YAML 节点树保留在 Raw 字段。
type TemplateDocument struct {
	// Path 是加载/保存的绝对路径。
	Path string `json:"path"`
	// ContentHash 是 Path 指向文件原始内容的 SHA-256（UTF-8 字节）。
	ContentHash string `json:"contentHash"`
	// Config 是从 YAML 中抽取出的规范化字段（用于前端展示与编辑）。
	// 注意：当字段在 YAML 中缺失时，会以 Python 组件 default_params 填入，
	// 但 Presence 字段会标记该值是否来自磁盘。
	Config TemplateConfig `json:"config"`
	// Presence 记录每个白名单字段是否真的出现在 YAML 文件中。
	// Save 时只有同时在 modifiedPaths 里的字段会被写回磁盘，避免引入新键。
	Presence FieldPresence `json:"presence"`
	// Topology 是固定拓扑的身份信息（只读，前端只能显示）。
	Topology TemplateTopology `json:"topology"`
	// Warnings 是加载过程中产生的非阻塞警告（例如 display_args 项无法解析）。
	Warnings []string `json:"warnings"`
	// Raw 是原始 YAML 节点树，保存时直接复用以保留注释与未知键。
	// 该字段不通过 Wails 返回给前端。
	Raw *yaml.Node `json:"-"`
}

// FieldPresence 标记白名单字段是否真实存在于 YAML 中。
// Presence 由加载阶段填充；保存阶段不再重新推断。
type FieldPresence struct {
	CycleTime  bool          `json:"cycleTime"`
	ClockMode  bool          `json:"clockMode"`
	SourceFlow bool          `json:"sourceFlow"`
	Valve      ValvePresence `json:"valve"`
	Tank1      TankPresence  `json:"tank1"`
	Tank2      TankPresence  `json:"tank2"`
	PID        PIDPresence   `json:"pid"`
}

type ValvePresence struct {
	FullTravelTime  bool `json:"fullTravelTime"`
	InitialOpening  bool `json:"initialOpening"`
	FlowCoefficient bool `json:"flowCoefficient"`
	MinOpening      bool `json:"minOpening"`
	MaxOpening      bool `json:"maxOpening"`
}

type TankPresence struct {
	Height       bool `json:"height"`
	Radius       bool `json:"radius"`
	OutletArea   bool `json:"outletArea"`
	InitialLevel bool `json:"initialLevel"`
}

// PIDPresence 中 PV/AUTO/CAS 故意不暴露为白名单可写字段，永远保持 false。
type PIDPresence struct {
	PB    bool `json:"PB"`
	TI    bool `json:"TI"`
	TD    bool `json:"TD"`
	KD    bool `json:"KD"`
	SV    bool `json:"SV"`
	MV    bool `json:"MV"`
	MODE  bool `json:"MODE"`
	SWPN  bool `json:"SWPN"`
	SVSCL bool `json:"SVSCL"`
	SVSCH bool `json:"SVSCH"`
	SVL   bool `json:"SVL"`
	SVH   bool `json:"SVH"`
	MVSCL bool `json:"MVSCL"`
	MVSCH bool `json:"MVSCH"`
	MVL   bool `json:"MVL"`
	MVH   bool `json:"MVH"`
}

// TemplateConfig 是规范化的可编辑字段集合。
// 单位换算在展示层完成，DSL 文件本身始终以工程单位保存。
type TemplateConfig struct {
	CycleTime  float64     `json:"cycleTime"`
	ClockMode  string      `json:"clockMode"`
	SourceFlow float64     `json:"sourceFlow"`
	Valve      ValveConfig `json:"valve"`
	Tank1      TankConfig  `json:"tank1"`
	Tank2      TankConfig  `json:"tank2"`
	PID        PIDConfig   `json:"pid"`
}

// ValveConfig 描述调节阀 valve_1 的组态字段。
// 缺失字段在 extractValve 中按 Python VALVE.default_params 填充。
type ValveConfig struct {
	FullTravelTime  float64 `json:"fullTravelTime"`
	InitialOpening  float64 `json:"initialOpening"`
	FlowCoefficient float64 `json:"flowCoefficient"`
	MinOpening      float64 `json:"minOpening"`
	MaxOpening      float64 `json:"maxOpening"`
}

// TankConfig 描述圆柱形水箱的高度、半径、出口面积与初始液位。
type TankConfig struct {
	Height       float64 `json:"height"`
	Radius       float64 `json:"radius"`
	OutletArea   float64 `json:"outletArea"`
	InitialLevel float64 `json:"initialLevel"`
}

// PIDConfig 描述 PID pid2 的可持久化参数白名单。
// 在线调参的临时 MV 与 PV 不进入此处。
type PIDConfig struct {
	PB    float64 `json:"PB"`
	TI    float64 `json:"TI"`
	TD    float64 `json:"TD"`
	KD    float64 `json:"KD"`
	SV    float64 `json:"SV"`
	MV    float64 `json:"MV"`
	MODE  int     `json:"MODE"`
	SWPN  int     `json:"SWPN"`
	SVSCL float64 `json:"SVSCL"`
	SVSCH float64 `json:"SVSCH"`
	SVL   float64 `json:"SVL"`
	SVH   float64 `json:"SVH"`
	MVSCL float64 `json:"MVSCL"`
	MVSCH float64 `json:"MVSCH"`
	MVL   float64 `json:"MVL"`
	MVH   float64 `json:"MVH"`
}

// TemplateTopology 描述固定身份信息，name/type/inputs/execute_first 全部只读。
type TemplateTopology struct {
	Programs []TemplateProgramTopology `json:"programs"`
}

// TemplateProgramTopology 是单个 program 的只读身份。
type TemplateProgramTopology struct {
	Name         string            `json:"name"`
	Type         string            `json:"type"`
	Inputs       map[string]string `json:"inputs"`
	ExecuteFirst bool              `json:"executeFirst"`
}

// TemplatePatch 是一个最小白名单写入单元。
// Path 形如 "tank1.height"、"pid.PB"、"sourceFlow"，由前端 store 统一产生。
// Value 在持久化前需通过 ValidateTemplateConfig 做范围与跨字段校验。
type TemplatePatch struct {
	Path  string  `json:"path"`
	Value float64 `json:"value"`
}

// SaveTemplateRequest 是保存请求。
type SaveTemplateRequest struct {
	SourcePath     string          `json:"sourcePath"`
	TargetPath     string          `json:"targetPath"`
	ExpectedHash   string          `json:"expectedHash"`
	Patches        []TemplatePatch `json:"patches"`
	AllowOverwrite bool            `json:"allowOverwrite"`
}

// SaveTemplateResult 是保存结果。
type SaveTemplateResult struct {
	NewPath     string           `json:"newPath"`
	NewHash     string           `json:"newHash"`
	NewDocument TemplateDocument `json:"newDocument"`
}

// BuiltinTemplateRelativePath 是相对仓库根的内置模板路径。
// 阶段 1 唯一内置模板。
const BuiltinTemplateRelativePath = "config/单阀门二阶水箱.yaml"

// TemplateState 是模板运行/编辑状态机（前端使用）。
type TemplateState string

const (
	TemplateStateStoppedEditing  TemplateState = "STOPPED_EDITING"
	TemplateStateStarting        TemplateState = "STARTING"
	TemplateStateSimRunning      TemplateState = "SIMULATION_RUNNING"
	TemplateStateRealtimeRunning TemplateState = "REALTIME_RUNNING"
	TemplateStateBatchRunning    TemplateState = "BATCH_RUNNING"
	TemplateStateStopping        TemplateState = "STOPPING"
	TemplateStateError           TemplateState = "ERROR"
)

// RunningConfigIdentity 记录当前运行实例采用的配置指纹。
// 前端用它判断 savedEqualsRunning，并在 UI 上明确区分。
type RunningConfigIdentity struct {
	Path        string    `json:"path"`
	ContentHash string    `json:"contentHash"`
	StartedAt   time.Time `json:"startedAt"`
}
