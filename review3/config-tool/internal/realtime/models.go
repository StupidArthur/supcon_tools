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
	Project    Project          `json:"project"`
	Validation ValidationResult `json:"validation"`
}
