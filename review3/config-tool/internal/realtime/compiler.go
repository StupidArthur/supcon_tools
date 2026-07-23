package realtime

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
)

type CompilerSourceSpec struct {
	ID       string `json:"id"`
	File     string `json:"file"`
	Replicas int    `json:"replicas"`
}

type RealtimeCompiler interface {
	Validate(ctx context.Context, sources []CompilerSourceSpec) (ValidationResult, error)
	Compile(ctx context.Context, sources []CompilerSourceSpec, outputPath string) (string, error)
}

type PythonRealtimeCompiler struct {
	exec *dataFactoryExec
}

type dataFactoryExec struct {
	exe        string
	prefixArgs []string
	workDir    string
}

func NewPythonRealtimeCompiler(exe string, prefixArgs []string, workDir string) *PythonRealtimeCompiler {
	return &PythonRealtimeCompiler{
		exec: &dataFactoryExec{exe: exe, prefixArgs: prefixArgs, workDir: workDir},
	}
}

type cliInput struct {
	Sources []CompilerSourceSpec `json:"sources"`
}

type cliOutput struct {
	OK         bool                `json:"ok"`
	Valid      bool                `json:"valid"`
	Instances  []ExpandedInstance  `json:"instances"`
	Duplicates []DuplicateInstance `json:"duplicates"`
	Error      *cliError           `json:"error,omitempty"`
}

type cliError struct {
	Code       string `json:"code"`
	Message    string `json:"message"`
	SourceID   string `json:"sourceId,omitempty"`
	SourceFile string `json:"sourceFile,omitempty"`
	Detail     string `json:"detail,omitempty"`
}

func (c *PythonRealtimeCompiler) Validate(ctx context.Context, sources []CompilerSourceSpec) (ValidationResult, error) {
	input := cliInput{Sources: sources}
	inputJSON, err := json.Marshal(input)
	if err != nil {
		return ValidationResult{}, fmt.Errorf("序列化输入失败: %w", err)
	}

	allArgs := append(append([]string{}, c.exec.prefixArgs...), "--inspect-project")
	cmd := exec.CommandContext(ctx, c.exec.exe, allArgs...)
	if c.exec.workDir != "" {
		cmd.Dir = c.exec.workDir
	}

	var stdout, stderr bytes.Buffer
	cmd.Stdin = bytes.NewReader(inputJSON)
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	runErr := cmd.Run()

	if runErr != nil {
		var out cliOutput
		if jsonErr := json.Unmarshal(stdout.Bytes(), &out); jsonErr == nil && out.Error != nil {
			return ValidationResult{}, &ValidationError{
				Code:    out.Error.Code,
				Message: out.Error.Message,
			}
		}
		stderrSnippet := stderr.String()
		if len(stderrSnippet) > 512 {
			stderrSnippet = stderrSnippet[:512]
		}
		return ValidationResult{}, fmt.Errorf("Python 校验进程失败: %w\nstderr: %s", runErr, stderrSnippet)
	}

	var out cliOutput
	if err := json.Unmarshal(stdout.Bytes(), &out); err != nil {
		stderrSnippet := stderr.String()
		if len(stderrSnippet) > 512 {
			stderrSnippet = stderrSnippet[:512]
		}
		return ValidationResult{}, fmt.Errorf("解析 Python 输出失败: %w\nstdout: %s\nstderr: %s", err, stdout.String(), stderrSnippet)
	}

	if !out.OK {
		msg := "未知错误"
		code := "UNKNOWN"
		if out.Error != nil {
			msg = out.Error.Message
			code = out.Error.Code
		}
		return ValidationResult{}, &ValidationError{Code: code, Message: msg}
	}

	result := ValidationResult{
		Valid:      out.Valid,
		Instances:  out.Instances,
		Duplicates: out.Duplicates,
	}
	if result.Instances == nil {
		result.Instances = []ExpandedInstance{}
	}
	if result.Duplicates == nil {
		result.Duplicates = []DuplicateInstance{}
	}
	return result, nil
}

type compileInput struct {
	Sources []CompilerSourceSpec `json:"sources"`
	Output  string               `json:"output"`
}

type compileOutput struct {
	OK     bool      `json:"ok"`
	Output string    `json:"output,omitempty"`
	Error  *cliError `json:"error,omitempty"`
}

func (c *PythonRealtimeCompiler) Compile(ctx context.Context, sources []CompilerSourceSpec, outputPath string) (string, error) {
	input := compileInput{Sources: sources, Output: outputPath}
	inputJSON, err := json.Marshal(input)
	if err != nil {
		return "", fmt.Errorf("序列化输入失败: %w", err)
	}

	allArgs := append(append([]string{}, c.exec.prefixArgs...), "--compile-project")
	cmd := exec.CommandContext(ctx, c.exec.exe, allArgs...)
	if c.exec.workDir != "" {
		cmd.Dir = c.exec.workDir
	}

	var stdout, stderr bytes.Buffer
	cmd.Stdin = bytes.NewReader(inputJSON)
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	runErr := cmd.Run()

	if runErr != nil {
		var out compileOutput
		if jsonErr := json.Unmarshal(stdout.Bytes(), &out); jsonErr == nil && out.Error != nil {
			return "", &ValidationError{Code: out.Error.Code, Message: out.Error.Message}
		}
		stderrSnippet := stderr.String()
		if len(stderrSnippet) > 512 {
			stderrSnippet = stderrSnippet[:512]
		}
		return "", fmt.Errorf("Python 编译进程失败: %w\nstderr: %s", runErr, stderrSnippet)
	}

	var out compileOutput
	if err := json.Unmarshal(stdout.Bytes(), &out); err != nil {
		return "", fmt.Errorf("解析 Python 编译输出失败: %w\nstdout: %s", err, stdout.String())
	}
	if !out.OK {
		msg := "未知错误"
		code := "UNKNOWN"
		if out.Error != nil {
			msg = out.Error.Message
			code = out.Error.Code
		}
		return "", &ValidationError{Code: code, Message: msg}
	}
	return out.Output, nil
}
