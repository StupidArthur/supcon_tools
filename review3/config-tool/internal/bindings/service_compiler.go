package bindings

import (
	"context"
	"fmt"
	"sync"

	"config-tool/internal/realtime"
)

// ServiceRealtimeCompiler 通过常驻服务 API 执行校验和编译（todo.md §7.1）。
type ServiceRealtimeCompiler struct {
	client      *DataFactoryServiceClient
	mu          sync.Mutex
	projectFile string
}

func NewServiceRealtimeCompiler(client *DataFactoryServiceClient) *ServiceRealtimeCompiler {
	return &ServiceRealtimeCompiler{client: client}
}

// SetProjectFile 设置当前工程文件路径，校验/编译时传给服务端。
func (c *ServiceRealtimeCompiler) SetProjectFile(path string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.projectFile = path
}

type inspectSource struct {
	ID       string `json:"id"`
	File     string `json:"file"`
	Replicas int    `json:"replicas"`
}

type inspectRequest struct {
	Sources     []inspectSource `json:"sources"`
	ProjectFile string          `json:"projectFile,omitempty"`
}

type inspectResponse struct {
	OK         bool                        `json:"ok"`
	Valid      bool                        `json:"valid"`
	Instances  []realtime.ExpandedInstance  `json:"instances"`
	Duplicates []realtime.DuplicateInstance `json:"duplicates"`
}

func (c *ServiceRealtimeCompiler) Validate(ctx context.Context, sources []realtime.CompilerSourceSpec) (realtime.ValidationResult, error) {
	c.mu.Lock()
	pf := c.projectFile
	c.mu.Unlock()

	req := inspectRequest{
		Sources:     make([]inspectSource, len(sources)),
		ProjectFile: pf,
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
	Sources     []inspectSource `json:"sources"`
	Output      string          `json:"output"`
	ProjectFile string          `json:"projectFile,omitempty"`
}

type compileResponse struct {
	OK     bool   `json:"ok"`
	Output string `json:"output"`
}

func (c *ServiceRealtimeCompiler) Compile(ctx context.Context, sources []realtime.CompilerSourceSpec, outputPath string) (string, error) {
	c.mu.Lock()
	pf := c.projectFile
	c.mu.Unlock()

	req := compileRequest{
		Sources:     make([]inspectSource, len(sources)),
		Output:      outputPath,
		ProjectFile: pf,
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
