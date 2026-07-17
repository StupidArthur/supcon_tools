package config

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"gopkg.in/yaml.v3"
)

func isVariableType(typeStr string) bool {
	t := strings.ToUpper(typeStr)
	return t == "VARIABLE" || t == "EXPRESSION" || t == "LAG"
}

type Service struct{}

func NewService() *Service {
	return &Service{}
}

func (s *Service) ExportYAML(canvas CanvasState, path string) error {
	sorted, err := topologicalSort(canvas.Nodes, canvas.Edges)
	if err != nil {
		return err
	}

	nameByID := make(map[string]string)
	typeByID := make(map[string]string)
	for _, node := range canvas.Nodes {
		nameByID[node.ID] = node.Name
		typeByID[node.ID] = node.Type
	}

	program := make([]map[string]any, 0, len(sorted))
	for _, node := range sorted {
		program = append(program, buildProgramItem(node, canvas.Edges, nameByID, typeByID))
	}

	config := map[string]any{
		"clock": map[string]any{
			"mode":       canvas.Clock.Mode,
			"cycle_time": canvas.Clock.CycleTime,
		},
		"program": program,
	}

	var buf bytes.Buffer
	encoder := yaml.NewEncoder(&buf)
	encoder.SetIndent(2)
	if err := encoder.Encode(config); err != nil {
		return fmt.Errorf("YAML 序列化失败: %w", err)
	}
	encoder.Close()

	if err := os.WriteFile(path, buf.Bytes(), 0644); err != nil {
		return fmt.Errorf("写入文件失败: %w", err)
	}
	return nil
}

func buildProgramItem(node BlockNode, edges []Connection, nameByID map[string]string, typeByID map[string]string) map[string]any {
	item := map[string]any{
		"name": node.Name,
		"type": node.Type,
	}

	typeUpper := strings.ToUpper(node.Type)

	switch typeUpper {
	case "VARIABLE":
		if v, ok := node.Params["value"]; ok {
			item["value"] = v
		}
	case "EXPRESSION":
		if v, ok := node.Params["formula"]; ok {
			item["formula"] = v
		}
	case "LAG":
		if v, ok := node.Params["source"]; ok {
			item["source"] = v
		}
		if v, ok := node.Params["delay"]; ok {
			item["delay"] = v
		}
	default:
		if len(node.Params) > 0 {
			item["params"] = node.Params
		}
		inputs := map[string]string{}
		for _, edge := range edges {
			if edge.Target == node.ID {
				sourceName := nameByID[edge.Source]
				if sourceName == "" {
					sourceName = edge.Source
				}
				if isVariableType(typeByID[edge.Source]) {
					inputs[edge.TargetPort] = sourceName
				} else {
					inputs[edge.TargetPort] = sourceName + "." + edge.SourcePort
				}
			}
		}
		if len(inputs) > 0 {
			item["inputs"] = inputs
		}
	}

	if node.ExecuteFirst {
		item["execute_first"] = true
	}

	return item
}

func (s *Service) ImportYAML(path string) (CanvasState, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return CanvasState{}, fmt.Errorf("读取文件失败: %w", err)
	}

	var yamlConfig struct {
		Clock struct {
			Mode      string  `yaml:"mode"`
			CycleTime float64 `yaml:"cycle_time"`
		} `yaml:"clock"`
		Program []map[string]any `yaml:"program"`
	}

	if err := yaml.Unmarshal(data, &yamlConfig); err != nil {
		return CanvasState{}, fmt.Errorf("YAML 解析失败: %w", err)
	}

	canvas := CanvasState{
		Clock: ClockConfig{
			Mode:      yamlConfig.Clock.Mode,
			CycleTime: yamlConfig.Clock.CycleTime,
		},
	}

	var nodes []BlockNode
	var edges []Connection

	for i, item := range yamlConfig.Program {
		name, _ := item["name"].(string)
		typeStr, _ := item["type"].(string)

		node := BlockNode{
			ID:       name,
			Name:     name,
			Type:     typeStr,
			Position: Position{X: float64(i%3) * 250, Y: float64(i/3) * 150},
			Params:   map[string]any{},
		}

		typeUpper := strings.ToUpper(typeStr)

		switch typeUpper {
		case "VARIABLE":
			if v, ok := item["value"]; ok {
				node.Params["value"] = v
			}
		case "EXPRESSION":
			if v, ok := item["formula"]; ok {
				node.Params["formula"] = v
			}
		case "LAG":
			if v, ok := item["source"]; ok {
				node.Params["source"] = v
			}
			if v, ok := item["delay"]; ok {
				node.Params["delay"] = v
			}
		default:
			if params, ok := item["params"].(map[string]any); ok {
				node.Params = params
			} else if initArgs, ok := item["init_args"].(map[string]any); ok {
				node.Params = initArgs
			}
			if inputs, ok := item["inputs"].(map[string]any); ok {
				for targetPort, sourceExpr := range inputs {
					sourceStr, _ := sourceExpr.(string)
					parts := strings.SplitN(sourceStr, ".", 2)
					sourceName := parts[0]
					sourcePort := ""
					if len(parts) > 1 {
						sourcePort = parts[1]
					}
					edges = append(edges, Connection{
						ID:         sourceName + "." + sourcePort + "-" + name + "." + targetPort,
						Source:     sourceName,
						SourcePort: sourcePort,
						Target:     name,
						TargetPort: targetPort,
					})
				}
			}
		}

		if ef, ok := item["execute_first"].(bool); ok {
			node.ExecuteFirst = ef
		}

		nodes = append(nodes, node)
	}

	// Fix sourcePort for Variable/Expression/Lag sources (no ".out" in YAML)
	typeByID := make(map[string]string)
	for _, n := range nodes {
		typeByID[n.ID] = n.Type
	}
	for i := range edges {
		if edges[i].SourcePort == "" && isVariableType(typeByID[edges[i].Source]) {
			edges[i].SourcePort = "out"
		}
	}

	canvas.Nodes = nodes
	canvas.Edges = edges
	return canvas, nil
}

func (s *Service) Validate(canvas CanvasState) (ValidationResult, error) {
	result := ValidationResult{
		Valid:    true,
		Errors:   []string{},
		Warnings: []string{},
	}

	names := make(map[string]bool)
	for _, node := range canvas.Nodes {
		if names[node.Name] {
			result.Valid = false
			result.Errors = append(result.Errors, "节点名称冲突: "+node.Name)
		}
		names[node.Name] = true
	}

	if _, err := topologicalSort(canvas.Nodes, canvas.Edges); err != nil {
		result.Valid = false
		result.Errors = append(result.Errors, err.Error())
	}

	for _, edge := range canvas.Edges {
		if !names[edge.Source] {
			result.Warnings = append(result.Warnings, "连线引用了不存在的节点: "+edge.Source)
		}
		if !names[edge.Target] {
			result.Warnings = append(result.Warnings, "连线引用了不存在的节点: "+edge.Target)
		}
	}

	return result, nil
}

func (s *Service) SaveCanvas(canvas CanvasState, path string) error {
	data, err := json.MarshalIndent(canvas, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0644)
}

func (s *Service) LoadCanvas(path string) (CanvasState, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return CanvasState{}, err
	}
	var canvas CanvasState
	if err := json.Unmarshal(data, &canvas); err != nil {
		return CanvasState{}, err
	}
	return canvas, nil
}
