package realtime

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/google/uuid"
)

type Manager struct {
	storage   *ProjectStorage
	compiler  RealtimeCompiler
	mu        sync.Mutex
	locations map[string]string // projectID -> project.yaml 绝对路径
}

// NewManager 接受旧式 storage（基于 root 目录的工程集合）。
// 新页面通过 CreateProjectAt / OpenProjectFile 走 locations map，
// 不再依赖 storage.root 列出工程。
func NewManager(storage *ProjectStorage, compiler RealtimeCompiler) *Manager {
	return &Manager{
		storage:   storage,
		compiler:  compiler,
		locations: make(map[string]string),
	}
}

func (m *Manager) ListProjects(_ context.Context) ([]ProjectSummary, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.storage.ListProjects()
}

// CreateProjectAt 在用户选择的 parentDir 下创建工程目录：
// <parentDir>/<safeName>/project.yaml + sources/。
// 返回 OpenedProject，附带绝对路径。
func (m *Manager) CreateProjectAt(_ context.Context, name, parentDir string) (OpenedProject, error) {
	if strings.TrimSpace(name) == "" {
		return OpenedProject{}, fmt.Errorf("工程名称不能为空")
	}
	if strings.TrimSpace(parentDir) == "" {
		return OpenedProject{}, fmt.Errorf("工程父目录不能为空")
	}
	if !isValidID(sanitizeNameForDir(name)) {
		return OpenedProject{}, fmt.Errorf("工程名称包含非法文件名字符")
	}
	dirName := sanitizeNameForDir(name)
	targetDir := filepath.Join(parentDir, dirName)
	if info, err := os.Stat(targetDir); err == nil && info.IsDir() {
		// 目录已存在且非空 → 拒绝
		if !isEmptyDir(targetDir) {
			return OpenedProject{}, fmt.Errorf("目标工程目录已存在且非空: %s", targetDir)
		}
	}
	if err := os.MkdirAll(filepath.Join(targetDir, "sources"), 0o755); err != nil {
		return OpenedProject{}, fmt.Errorf("创建工程目录失败: %w", err)
	}
	id := uuid.New().String()
	// 写入 runtime 默认值（设计文档 §5.7 示例字段）。前端不再单独提供运行参数输入，
	// 必须保证 project.yaml 从创建起就带有合法默认 runtime，避免后续打开得到空值。
	p := Project{
		Version: 1,
		ID:      id,
		Name:    name,
		Sources: []Source{},
		Runtime: &Runtime{
			CycleTime: 0.5,
			OPCUAHost: "0.0.0.0",
			OPCUAPort: 18951,
		},
	}
	projectFile := filepath.Join(targetDir, "project.yaml")
	if err := SaveProjectToFile(projectFile, p); err != nil {
		_ = os.RemoveAll(targetDir)
		return OpenedProject{}, fmt.Errorf("写入工程文件失败: %w", err)
	}
	m.mu.Lock()
	m.locations[id] = projectFile
	m.mu.Unlock()
	return OpenedProject{
		Project:     p,
		ProjectFile: projectFile,
		ProjectDir:  targetDir,
	}, nil
}

// OpenProjectFile 打开用户选择的本地 project.yaml。
// 必须满足设计文档 §5.4 的全部硬性校验：文件可读、YAML 可解析、ID 合法、
// source 路径在工程目录内且存在、副本数在限值内、实例展开无冲突。
func (m *Manager) OpenProjectFile(_ context.Context, projectFile string) (OpenedProject, error) {
	if strings.TrimSpace(projectFile) == "" {
		return OpenedProject{}, fmt.Errorf("工程文件路径不能为空")
	}
	absPath, err := filepath.Abs(projectFile)
	if err != nil {
		return OpenedProject{}, fmt.Errorf("解析工程路径失败: %w", err)
	}
	p, err := LoadProjectFile(absPath)
	if err != nil {
		return OpenedProject{}, err
	}
	if strings.TrimSpace(p.Name) == "" {
		return OpenedProject{}, fmt.Errorf("工程名称不能为空")
	}
	projectDir := filepath.Dir(absPath)
	// source 路径必须在工程目录内
	for _, s := range p.Sources {
		if strings.TrimSpace(s.ID) == "" || !isValidID(s.ID) {
			return OpenedProject{}, fmt.Errorf("非法 source ID: %q", s.ID)
		}
		if strings.TrimSpace(s.File) == "" {
			return OpenedProject{}, fmt.Errorf("source %s 缺少 file", s.ID)
		}
		abs := filepath.Join(projectDir, s.File)
		if !strings.HasPrefix(filepath.Clean(abs), filepath.Clean(projectDir)) {
			return OpenedProject{}, fmt.Errorf("source %s 路径在工程目录之外", s.ID)
		}
		if _, err := os.Stat(abs); err != nil {
			return OpenedProject{}, fmt.Errorf("source 文件不存在: %s", abs)
		}
		if s.Replicas < MinReplicas || s.Replicas > MaxReplicas {
			return OpenedProject{}, fmt.Errorf("source %s 副本数超出范围", s.ID)
		}
	}
	// 编译校验
	specs := make([]CompilerSourceSpec, len(p.Sources))
	for i, s := range p.Sources {
		specs[i] = CompilerSourceSpec{
			ID:       s.ID,
			File:     filepath.Join(projectDir, s.File),
			Replicas: s.Replicas,
		}
	}
	if len(specs) > 0 {
		if _, err := m.compiler.Validate(context.Background(), specs); err != nil {
			return OpenedProject{}, fmt.Errorf("工程校验失败: %w", err)
		}
	}
	m.mu.Lock()
	m.locations[p.ID] = absPath
	m.mu.Unlock()
	return OpenedProject{
		Project:     p,
		ProjectFile: absPath,
		ProjectDir:  projectDir,
	}, nil
}

// resolveProjectFile 返回 projectID 对应的 project.yaml 绝对路径，
// 不在 locations 时回退到 storage.projectFile(id)。
// 调用方必须未持有 m.mu。
func (m *Manager) resolveProjectFile(projectID string) (string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.resolveProjectFileLocked(projectID)
}

// resolveProjectFileLocked 调用方必须已持有 m.mu。
func (m *Manager) resolveProjectFileLocked(projectID string) (string, error) {
	if p, ok := m.locations[projectID]; ok {
		return p, nil
	}
	if !m.storage.ProjectExists(projectID) {
		return "", fmt.Errorf("工程不存在: %s", projectID)
	}
	return m.storage.projectFile(projectID), nil
}

func (m *Manager) CreateProject(_ context.Context, name string) (Project, error) {
	if name == "" {
		return Project{}, fmt.Errorf("工程名称不能为空")
	}
	m.mu.Lock()
	defer m.mu.Unlock()

	id := uuid.New().String()
	p := Project{
		Version: 1,
		ID:      id,
		Name:    name,
		Sources: []Source{},
	}
	if err := m.storage.SaveProject(p); err != nil {
		return Project{}, err
	}
	return p, nil
}

func (m *Manager) OpenProject(_ context.Context, id string) (Project, error) {
	m.mu.Lock()
	if pf, ok := m.locations[id]; ok {
		m.mu.Unlock()
		return LoadProjectFile(pf)
	}
	m.mu.Unlock()
	// 兼容旧 storage 工程；新工程必须走 OpenProjectFile 并已写入 locations
	return m.storage.LoadProject(id)
}

func (m *Manager) DeleteProject(_ context.Context, id string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.locations, id)
	// 同时尝试清理旧 storage（不存在时静默忽略）
	if err := m.storage.DeleteProject(id); err != nil {
		// 旧 storage 中可能不存在该工程（locations-only 工程），仅记录
		_ = err
	}
	return nil
}

func (m *Manager) RenameProject(_ context.Context, id, newName string) (Project, error) {
	if newName == "" {
		return Project{}, fmt.Errorf("工程名称不能为空")
	}
	m.mu.Lock()
	defer m.mu.Unlock()

	if pf, ok := m.locations[id]; ok {
		p, err := LoadProjectFile(pf)
		if err != nil {
			return Project{}, err
		}
		p.Name = newName
		if err := SaveProjectToFile(pf, p); err != nil {
			return Project{}, err
		}
		return p, nil
	}
	// 旧 storage 路径（仅兜底）
	p, err := m.storage.LoadProject(id)
	if err != nil {
		return Project{}, err
	}
	p.Name = newName
	if err := m.storage.SaveProject(p); err != nil {
		return Project{}, err
	}
	return p, nil
}

// AddSource 在指定 projectID 对应的工程目录下，复制外部 yaml 到 sources/<sourceID>.yaml。
// projectID 必须已经通过 CreateProjectAt / OpenProjectFile 注册到 locations，
// 否则按 storage 旧式 root 路径处理（兼容旧测试）。
func (m *Manager) AddSource(ctx context.Context, projectID, yamlPath string) (ProjectView, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	projectFile, err := m.resolveProjectFileLocked(projectID)
	if err != nil {
		return ProjectView{}, err
	}
	projectDir := filepath.Dir(projectFile)
	p, err := LoadProjectFile(projectFile)
	if err != nil {
		return ProjectView{}, err
	}

	sourceID := uuid.New().String()
	baseName := filepath.Base(yamlPath)
	target := filepath.Join(projectDir, "sources", sourceID+".yaml")

	if err := copyYAMLFile(yamlPath, target); err != nil {
		return ProjectView{}, err
	}

	candidate := make([]Source, len(p.Sources), len(p.Sources)+1)
	copy(candidate, p.Sources)
	candidate = append(candidate, Source{
		ID:       sourceID,
		Name:     baseName,
		File:     "sources/" + sourceID + ".yaml",
		Replicas: 1,
	})

	result, err := m.validateCandidateAt(ctx, projectDir, candidate)
	if err != nil {
		_ = os.Remove(target)
		return ProjectView{}, err
	}
	if !result.Valid {
		_ = os.Remove(target)
		return ProjectView{Applied: false, Project: p, Validation: result}, nil
	}

	p.Sources = candidate
	if err := SaveProjectToFile(projectFile, p); err != nil {
		_ = os.Remove(target)
		return ProjectView{}, err
	}

	return ProjectView{Applied: true, Project: p, Validation: result}, nil
}

// AddSourceAt 在指定 projectFile 下添加 YAML（不走 storage 路径）。
// 返回 OpenedProjectView。
func (m *Manager) AddSourceAt(ctx context.Context, projectID, projectFile, yamlPath string) (OpenedProjectView, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	if projectFile == "" {
		return OpenedProjectView{}, fmt.Errorf("工程文件路径不能为空")
	}
	projectDir := filepath.Dir(projectFile)
	p, err := LoadProjectFile(projectFile)
	if err != nil {
		return OpenedProjectView{}, err
	}

	sourceID := uuid.New().String()
	baseName := filepath.Base(yamlPath)
	target := filepath.Join(projectDir, "sources", sourceID+".yaml")

	if err := copyYAMLFile(yamlPath, target); err != nil {
		return OpenedProjectView{}, err
	}

	candidate := make([]Source, len(p.Sources), len(p.Sources)+1)
	copy(candidate, p.Sources)
	candidate = append(candidate, Source{
		ID:       sourceID,
		Name:     baseName,
		File:     "sources/" + sourceID + ".yaml",
		Replicas: 1,
	})

	result, err := m.validateCandidateAt(ctx, projectDir, candidate)
	if err != nil {
		_ = os.Remove(target)
		return OpenedProjectView{}, err
	}
	if !result.Valid {
		_ = os.Remove(target)
		return OpenedProjectView{
			Applied:    false,
			Project:    OpenedProject{Project: p, ProjectFile: projectFile, ProjectDir: projectDir},
			Validation: result,
		}, nil
	}

	p.Sources = candidate
	if err := SaveProjectToFile(projectFile, p); err != nil {
		_ = os.Remove(target)
		return OpenedProjectView{}, err
	}
	if projectID != "" {
		m.locations[projectID] = projectFile
	}
	return OpenedProjectView{
		Applied: true,
		Project: OpenedProject{Project: p, ProjectFile: projectFile, ProjectDir: projectDir},
		Validation: result,
	}, nil
}

// RemoveSourceAt / UpdateReplicasAt：与 AddSourceAt 同模式，
// 直接修改指定 projectFile 的 sources 列表。
func (m *Manager) RemoveSourceAt(ctx context.Context, projectID, projectFile, sourceID string) (OpenedProjectView, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.mutateSourcesAtLocked(ctx, projectID, projectFile, func(sources []Source) ([]Source, string, error) {
		var found bool
		out := make([]Source, 0, len(sources))
		for _, s := range sources {
			if s.ID == sourceID {
				found = true
				continue
			}
			out = append(out, s)
		}
		if !found {
			return nil, "", fmt.Errorf("来源不存在: %s", sourceID)
		}
		return out, sourceID, nil
	})
}

func (m *Manager) UpdateReplicasAt(ctx context.Context, projectID, projectFile, sourceID string, replicas int) (OpenedProjectView, error) {
	if replicas < MinReplicas || replicas > MaxReplicas {
		return OpenedProjectView{}, fmt.Errorf("副本数必须在 %d~%d 之间", MinReplicas, MaxReplicas)
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.mutateSourcesAtLocked(ctx, projectID, projectFile, func(sources []Source) ([]Source, string, error) {
		var found bool
		out := make([]Source, len(sources))
		copy(out, sources)
		for i := range out {
			if out[i].ID == sourceID {
				out[i].Replicas = replicas
				found = true
				break
			}
		}
		if !found {
			return nil, "", fmt.Errorf("来源不存在: %s", sourceID)
		}
		return out, "", nil
	})
}

func (m *Manager) mutateSourcesAtLocked(
	ctx context.Context,
	projectID, projectFile string,
	mutate func([]Source) ([]Source, string, error),
) (OpenedProjectView, error) {
	if projectFile == "" {
		return OpenedProjectView{}, fmt.Errorf("工程文件路径不能为空")
	}
	projectDir := filepath.Dir(projectFile)
	p, err := LoadProjectFile(projectFile)
	if err != nil {
		return OpenedProjectView{}, err
	}
	candidate, removedID, err := mutate(p.Sources)
	if err != nil {
		return OpenedProjectView{}, err
	}
	result, err := m.validateCandidateAt(ctx, projectDir, candidate)
	if err != nil {
		return OpenedProjectView{}, err
	}
	if !result.Valid {
		return OpenedProjectView{
			Applied:    false,
			Project:    OpenedProject{Project: p, ProjectFile: projectFile, ProjectDir: projectDir},
			Validation: result,
		}, nil
	}
	p.Sources = candidate
	if err := SaveProjectToFile(projectFile, p); err != nil {
		return OpenedProjectView{}, err
	}
	if removedID != "" {
		_ = os.Remove(filepath.Join(projectDir, "sources", removedID+".yaml"))
	}
	if projectID != "" {
		m.locations[projectID] = projectFile
	}
	return OpenedProjectView{
		Applied: true,
		Project: OpenedProject{Project: p, ProjectFile: projectFile, ProjectDir: projectDir},
		Validation: result,
	}, nil
}

// UpdateRuntimeAt 保存运行参数（周期 / UA 地址 / UA 端口）到指定工程文件。
// 仅修改 p.Runtime，不重建 sources。
func (m *Manager) UpdateRuntimeAt(_ context.Context, projectID, projectFile string, rt Runtime) (OpenedProject, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if projectFile == "" {
		return OpenedProject{}, fmt.Errorf("工程文件路径不能为空")
	}
	p, err := LoadProjectFile(projectFile)
	if err != nil {
		return OpenedProject{}, err
	}
	p.Runtime = &rt
	if err := SaveProjectToFile(projectFile, p); err != nil {
		return OpenedProject{}, err
	}
	if projectID != "" {
		m.locations[projectID] = projectFile
	}
	return OpenedProject{
		Project:     p,
		ProjectFile: projectFile,
		ProjectDir:  filepath.Dir(projectFile),
	}, nil
}

func (m *Manager) RemoveSource(ctx context.Context, projectID, sourceID string) (ProjectView, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	projectFile, err := m.resolveProjectFileLocked(projectID)
	if err != nil {
		return ProjectView{}, err
	}
	projectDir := filepath.Dir(projectFile)
	p, err := LoadProjectFile(projectFile)
	if err != nil {
		return ProjectView{}, err
	}

	found := false
	var newSources []Source
	for _, s := range p.Sources {
		if s.ID == sourceID {
			found = true
			continue
		}
		newSources = append(newSources, s)
	}
	if !found {
		return ProjectView{}, fmt.Errorf("来源不存在: %s", sourceID)
	}

	p.Sources = newSources
	if p.Sources == nil {
		p.Sources = []Source{}
	}

	result, err := m.validateCandidateAt(ctx, projectDir, p.Sources)
	if err != nil {
		return ProjectView{}, err
	}

	if err := SaveProjectToFile(projectFile, p); err != nil {
		return ProjectView{}, err
	}
	_ = os.Remove(filepath.Join(projectDir, "sources", sourceID+".yaml"))

	return ProjectView{Applied: true, Project: p, Validation: result}, nil
}

func (m *Manager) UpdateReplicas(ctx context.Context, projectID, sourceID string, replicas int) (ProjectView, error) {
	if replicas < MinReplicas || replicas > MaxReplicas {
		return ProjectView{}, fmt.Errorf("副本数必须在 %d~%d 之间", MinReplicas, MaxReplicas)
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	projectFile, err := m.resolveProjectFileLocked(projectID)
	if err != nil {
		return ProjectView{}, err
	}
	projectDir := filepath.Dir(projectFile)
	p, err := LoadProjectFile(projectFile)
	if err != nil {
		return ProjectView{}, err
	}

	found := false
	candidate := make([]Source, len(p.Sources))
	copy(candidate, p.Sources)
	for i := range candidate {
		if candidate[i].ID == sourceID {
			candidate[i].Replicas = replicas
			found = true
			break
		}
	}
	if !found {
		return ProjectView{}, fmt.Errorf("来源不存在: %s", sourceID)
	}

	result, err := m.validateCandidateAt(ctx, projectDir, candidate)
	if err != nil {
		return ProjectView{}, err
	}
	if !result.Valid {
		return ProjectView{Applied: false, Project: p, Validation: result}, nil
	}

	p.Sources = candidate
	if err := SaveProjectToFile(projectFile, p); err != nil {
		return ProjectView{}, err
	}

	return ProjectView{Applied: true, Project: p, Validation: result}, nil
}

func (m *Manager) ValidateProject(ctx context.Context, projectID string) (ValidationResult, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	projectFile, err := m.resolveProjectFileLocked(projectID)
	if err != nil {
		return ValidationResult{}, err
	}
	projectDir := filepath.Dir(projectFile)
	p, err := LoadProjectFile(projectFile)
	if err != nil {
		return ValidationResult{}, err
	}
	specs := make([]CompilerSourceSpec, len(p.Sources))
	for i, s := range p.Sources {
		specs[i] = CompilerSourceSpec{
			ID:       s.ID,
			File:     filepath.Join(projectDir, s.File),
			Replicas: s.Replicas,
		}
	}
	if len(specs) == 0 {
		return ValidationResult{Valid: true, Instances: []ExpandedInstance{}, Duplicates: []DuplicateInstance{}}, nil
	}
	return m.compiler.Validate(ctx, specs)
}

func (m *Manager) CompileProject(ctx context.Context, projectID, outputPath string) (string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	projectFile, err := m.resolveProjectFileLocked(projectID)
	if err != nil {
		return "", err
	}
	projectDir := filepath.Dir(projectFile)
	p, err := LoadProjectFile(projectFile)
	if err != nil {
		return "", err
	}
	if len(p.Sources) == 0 {
		return "", fmt.Errorf("工程没有 YAML 来源")
	}

	specs := make([]CompilerSourceSpec, len(p.Sources))
	for i, s := range p.Sources {
		specs[i] = CompilerSourceSpec{
			ID:       s.ID,
			File:     filepath.Join(projectDir, s.File),
			Replicas: s.Replicas,
		}
	}
	return m.compiler.Compile(ctx, specs, outputPath)
}

func (m *Manager) validateCandidate(ctx context.Context, projectID string, sources []Source) (ValidationResult, error) {
	if len(sources) == 0 {
		return ValidationResult{Valid: true, Instances: []ExpandedInstance{}, Duplicates: []DuplicateInstance{}}, nil
	}
	specs := make([]CompilerSourceSpec, len(sources))
	for i, s := range sources {
		specs[i] = CompilerSourceSpec{
			ID:       s.ID,
			File:     m.storage.SourceAbsPath(projectID, s.ID),
			Replicas: s.Replicas,
		}
	}
	return m.compiler.Validate(ctx, specs)
}

func (m *Manager) validateCandidateAt(ctx context.Context, projectDir string, sources []Source) (ValidationResult, error) {
	if len(sources) == 0 {
		return ValidationResult{Valid: true, Instances: []ExpandedInstance{}, Duplicates: []DuplicateInstance{}}, nil
	}
	specs := make([]CompilerSourceSpec, len(sources))
	for i, s := range sources {
		specs[i] = CompilerSourceSpec{
			ID:       s.ID,
			File:     filepath.Join(projectDir, s.File),
			Replicas: s.Replicas,
		}
	}
	return m.compiler.Validate(ctx, specs)
}

func (m *Manager) localValidation(_ []Source) ValidationResult {
	return ValidationResult{Valid: true, Instances: []ExpandedInstance{}, Duplicates: []DuplicateInstance{}}
}

// sanitizeNameForDir 把工程名转换为可在 Windows / Linux 创建目录的字符串。
// 去除 Windows 非法字符：\ / : * ? " < > |。
func sanitizeNameForDir(name string) string {
	invalid := []string{"\\", "/", ":", "*", "?", "\"", "<", ">", "|"}
	out := name
	for _, ch := range invalid {
		out = strings.ReplaceAll(out, ch, "_")
	}
	out = strings.TrimSpace(out)
	if out == "" {
		return "_"
	}
	return out
}

func isEmptyDir(dir string) bool {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return false
	}
	return len(entries) == 0
}

// copyYAMLFile 读取 src 写到 dst（atomic temp rename）。
func copyYAMLFile(src, dst string) error {
	data, err := os.ReadFile(src)
	if err != nil {
		return fmt.Errorf("读取源文件失败: %w", err)
	}
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	tmp := dst + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, dst)
}

// RuntimeRevision 重写为支持 locations map。
func (m *Manager) RuntimeRevision(projectID string) (string, error) {
	m.mu.Lock()
	projectFile, ok := m.locations[projectID]
	m.mu.Unlock()
	if !ok {
		// 回退到 storage 路径
		if !m.storage.ProjectExists(projectID) {
			return "", errors.New("工程不存在")
		}
		projectFile = m.storage.projectFile(projectID)
	}
	p, err := LoadProjectFile(projectFile)
	if err != nil {
		return "", err
	}
	projectDir := filepath.Dir(projectFile)
	return computeRevision(p, projectDir)
}

func computeRevision(p Project, projectDir string) (string, error) {
	h := newRevHash()
	fmt.Fprintf(h, "project:%s\n", p.ID)
	for _, s := range p.Sources {
		fmt.Fprintf(h, "source:%s|replicas:%d\n", s.ID, s.Replicas)
		data, err := os.ReadFile(filepath.Join(projectDir, s.File))
		if err != nil {
			return "", fmt.Errorf("read source file failed %s: %w", s.ID, err)
		}
		fh := sha256File(data)
		fmt.Fprintf(h, "filehash:%s\n", fh)
	}
	alarmsPath := filepath.Join(projectDir, "alarms.yaml")
	if data, err := os.ReadFile(alarmsPath); err == nil {
		ah := sha256File(data)
		fmt.Fprintf(h, "alarms:%s\n", ah)
	}
	return h.sum12(), nil
}