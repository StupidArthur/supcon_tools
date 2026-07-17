package config

import (
	"embed"
	"encoding/json"
	"fmt"
)

//go:embed components.json
var componentsFS embed.FS

func LoadComponentMetadata() ([]ComponentMeta, error) {
	data, err := componentsFS.ReadFile("components.json")
	if err != nil {
		return nil, fmt.Errorf("读取组件元数据失败: %w", err)
	}
	var metadata []ComponentMeta
	if err := json.Unmarshal(data, &metadata); err != nil {
		return nil, fmt.Errorf("解析组件元数据失败: %w", err)
	}
	return metadata, nil
}
