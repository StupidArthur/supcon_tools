package realtime

import "context"

// CompilerSourceSpec 定义单个编译源规格。
type CompilerSourceSpec struct {
	ID       string `json:"id"`
	File     string `json:"file"`
	Replicas int    `json:"replicas"`
}

// RealtimeCompiler 定义实时工程的校验和编译接口。
type RealtimeCompiler interface {
	Validate(ctx context.Context, sources []CompilerSourceSpec) (ValidationResult, error)
	Compile(ctx context.Context, sources []CompilerSourceSpec, outputPath string) (string, error)
}
