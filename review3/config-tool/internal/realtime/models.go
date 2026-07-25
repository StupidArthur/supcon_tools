package realtime

const (
	MinReplicas          = 1
	MaxReplicas          = 100
	MaxExpandedInstances = 50_000
)

type Source struct {
	ID       string `json:"id" yaml:"id"`
	Name     string `json:"name" yaml:"name"`
	File     string `json:"file" yaml:"file"`
	Replicas int    `json:"replicas" yaml:"replicas"`
}

type Project struct {
	Version int      `json:"version" yaml:"version"`
	ID      string   `json:"id" yaml:"id"`
	Name    string   `json:"name" yaml:"name"`
	Sources []Source `json:"sources" yaml:"sources"`
	Runtime *Runtime `json:"runtime,omitempty" yaml:"runtime,omitempty"`
}

// Runtime 描述运行时参数（控制周期、UA 地址、UA 端口）。
// 仅工程管理使用；不进入实时 session（实时 session 字段独立）。
type Runtime struct {
	CycleTime float64 `json:"cycleTime" yaml:"cycle_time"`
	OPCUAHost string  `json:"opcUaHost" yaml:"opcua_host"`
	OPCUAPort int     `json:"opcUaPort" yaml:"opcua_port"`
}

// OpenedProject 是返回给前端的工程快照。
// ProjectFile / ProjectDir 是内存中的派生字段，不写入 project.yaml。
type OpenedProject struct {
	Project     Project `json:"project" yaml:"project"`
	ProjectFile string  `json:"projectFile" yaml:"-"`
	ProjectDir  string  `json:"projectDir" yaml:"-"`
}

// OpenedProjectView 与 ProjectView 等价，但 Project 字段换为 OpenedProject。
type OpenedProjectView struct {
	Applied    bool                  `json:"applied" yaml:"applied"`
	Project    OpenedProject         `json:"project" yaml:"project"`
	Validation ValidationResult      `json:"validation" yaml:"validation"`
}

type ProjectSummary struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	SourceCount int    `json:"sourceCount"`
}

type InstanceOrigin struct {
	SourceID     string `json:"sourceId"`
	SourceFile   string `json:"sourceFile"`
	ReplicaIndex int    `json:"replicaIndex"`
	OriginalName string `json:"originalName"`
}

type ExpandedInstance struct {
	Name         string `json:"name"`
	SourceID     string `json:"sourceId"`
	SourceFile   string `json:"sourceFile"`
	ReplicaIndex int    `json:"replicaIndex"`
	OriginalName string `json:"originalName"`
}

type DuplicateInstance struct {
	Name        string           `json:"name"`
	Occurrences []InstanceOrigin `json:"occurrences"`
}

type ValidationResult struct {
	Valid      bool                `json:"valid"`
	Instances  []ExpandedInstance  `json:"instances"`
	Duplicates []DuplicateInstance `json:"duplicates"`
}

type ProjectView struct {
	Applied    bool             `json:"applied"`
	Project    Project          `json:"project"`
	Validation ValidationResult `json:"validation"`
}
