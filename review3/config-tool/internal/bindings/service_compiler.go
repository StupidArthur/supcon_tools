package bindings

import (
	"context"
	"fmt"

	"config-tool/internal/realtime"
)

// ServiceRealtimeCompiler 通过常驻服务 API 执行校验和编译（todo.md §7.1）。
type ServiceRealtimeCompiler struct {
	client *DataFactoryServiceClient
}

func NewServiceRealtimeCompiler(client *DataFactoryServiceClient) *ServiceRealtimeCompiler {
	return &ServiceRealtimeCompiler{client: client}
}

type inspectSource struct {
	ID       string `json:"id"`
	File     string `json:"file"`
	Replicas int    `json:"replicas"`
}

type inspectRequest struct {
	Sources []inspectSource `json:"sources"`
}

type inspectResponse struct {
	OK         bool                         `json:"ok"`
	Valid      bool                         `json:"valid"`
	Instances  []realtime.ExpandedInstance   `json:"instances"`
	Duplicates []realtime.DuplicateInstance `json:"duplicates"`
}

func (c *ServiceRealtimeCompiler) Validate(ctx context.Context, sources []realtime.CompilerSourceSpec) (realtime.ValidationResult, error) {
	req := inspectRequest{
		Sources: make([]inspectSource, len(sources)),
	}
	for i, s := range sources {
		req.Sources[i] = inspectSource{
			ID:       s.ID,
			File:     s.File,
			Replicas: s.Replicas,
		}
	}

	var resp inspectResponse
	if err := c.client.DoJSON(ctx, "POST", "/api/project/inspect", req, &resp); err != nil {
		return realtime.ValidationResult{}, fmt.Errorf("服务校验失败: %w", err)
	}

	result := realtime.ValidationResult{
		Valid:      resp.Valid,
		Instances:  resp.Instances,
		Duplicates: resp.Duplicates,
	}
	if result.Instances == nil {
		result.Instances = []realtime.ExpandedInstance{}
	}
	if result.Duplicates == nil {
		result.Duplicates = []realtime.DuplicateInstance{}
	}
	return result, nil
}

type compileRequest struct {
	Sources []inspectSource `json:"sources"`
	Output  string          `json:"output"`
}

type compileResponse struct {
	OK     bool   `json:"ok"`
	Output string `json:"output"`
}

func (c *ServiceRealtimeCompiler) Compile(ctx context.Context, sources []realtime.CompilerSourceSpec, outputPath string) (string, error) {
	req := compileRequest{
		Sources: make([]inspectSource, len(sources)),
		Output:  outputPath,
	}
	for i, s := range sources {
		req.Sources[i] = inspectSource{
			ID:       s.ID,
			File:     s.File,
			Replicas: s.Replicas,
		}
	}

	var resp compileResponse
	if err := c.client.DoJSON(ctx, "POST", "/api/project/compile", req, &resp); err != nil {
		return "", fmt.Errorf("服务编译失败: %w", err)
	}
	if !resp.OK {
		return "", fmt.Errorf("服务编译返回 ok=false")
	}
	return resp.Output, nil
}

var _ realtime.RealtimeCompiler = (*ServiceRealtimeCompiler)(nil)
