package ranking

import (
	"fmt"
	"sort"
)

// ParseRanking 解析 ranking/all 统一响应体 {code, message, data}。
// code=200 表示成功；data 为排名列表，按 rank 升序（同分按总分降序）返回。
func ParseRanking(res map[string]any) ([]Item, error) {
	code, _ := res["code"].(float64)
	if code != 200 {
		msg, _ := res["message"].(string)
		return nil, fmt.Errorf("ranking api failed: code=%v message=%s", res["code"], msg)
	}
	data, ok := res["data"].([]any)
	if !ok {
		return []Item{}, nil
	}
	items := make([]Item, 0, len(data))
	for _, raw := range data {
		m, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		it := Item{
			ControlScore:    optionalFloat(m["controlScore"]),
			SoftSensorScore: optionalFloat(m["softSensorScore"]),
		}
		if v, ok := m["rank"].(float64); ok {
			it.Rank = int(v)
		}
		if v, ok := m["tenantId"].(string); ok {
			it.TenantID = v
		}
		if v, ok := m["totalScore"].(float64); ok {
			it.TotalScore = v
		}
		items = append(items, it)
	}
	sort.SliceStable(items, func(i, j int) bool {
		if items[i].Rank != items[j].Rank {
			return items[i].Rank < items[j].Rank
		}
		return items[i].TotalScore > items[j].TotalScore
	})
	return items, nil
}

func optionalFloat(v any) *float64 {
	f, ok := v.(float64)
	if !ok {
		return nil
	}
	return &f
}

// AttachNames 按租户ID关联队伍名（无匹配时留空）。
func AttachNames(items []Item, names map[string]string) {
	for i := range items {
		items[i].Name = names[items[i].TenantID]
	}
}
