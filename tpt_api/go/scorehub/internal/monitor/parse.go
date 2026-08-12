package monitor

import (
	"fmt"
	"strconv"
)

// ParseQualities 解析 cub-data readValues 统一响应体，统计质量码。
// data 为列表，每项含 name/quality；quality==192 记 GOOD，其余进 badTags。
func ParseQualities(res map[string]any) (total, good int, badTags []string, err error) {
	code, _ := res["code"].(float64)
	if code != 200 {
		msg, _ := res["message"].(string)
		return 0, 0, nil, fmt.Errorf("readValues api failed: code=%v message=%s", res["code"], msg)
	}
	badTags = []string{}
	data, ok := res["data"].([]any)
	if !ok {
		return 0, 0, badTags, nil
	}
	for _, raw := range data {
		m, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		total++
		q, _ := m["quality"].(float64)
		if int(q) == QualityGood {
			good++
		} else {
			name, _ := m["name"].(string)
			badTags = append(badTags, name)
		}
	}
	return total, good, badTags, nil
}

// ExtractSample 从 readValues 响应中提取采样位号（SampleTagName）的值与时间戳。
// 值格式化为字符串；timeStamp（毫秒）原样返回，由前端按毫秒格式化。
func ExtractSample(res map[string]any) (value string, sampleTime string) {
	data, ok := res["data"].([]any)
	if !ok {
		return "", ""
	}
	for _, raw := range data {
		m, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		name, _ := m["name"].(string)
		if name != SampleTagName {
			continue
		}
		value = formatValue(m["value"])
		if ts, ok := m["timeStamp"].(float64); ok && ts > 0 {
			sampleTime = fmt.Sprintf("%d", int64(ts))
		}
		return value, sampleTime
	}
	return "", ""
}

// formatValue 把位号值（float64 或 string）格式化为紧凑字符串。
func formatValue(v any) string {
	switch x := v.(type) {
	case float64:
		return strconv.FormatFloat(x, 'f', -1, 64)
	case string:
		return x
	case nil:
		return ""
	default:
		return fmt.Sprintf("%v", v)
	}
}
