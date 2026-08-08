package personal

import "fmt"

// ParseDetail 解析 tenant-detail 统一响应体 {code, message, data}。
// data 形如 {tenantId, scoreRecords: [...], files: [...]}。
func ParseDetail(res map[string]any) (*Detail, error) {
	code, _ := res["code"].(float64)
	if code != 200 {
		msg, _ := res["message"].(string)
		return nil, fmt.Errorf("tenant-detail api failed: code=%v message=%s", res["code"], msg)
	}
	d := &Detail{ScoreRecords: []ScoreRecord{}, Files: []FileRecord{}}
	data, ok := res["data"].(map[string]any)
	if !ok {
		return d, nil
	}
	d.TenantID = asString(data["tenantId"])
	if arr, ok := data["scoreRecords"].([]any); ok {
		for _, raw := range arr {
			m, ok := raw.(map[string]any)
			if !ok {
				continue
			}
			d.ScoreRecords = append(d.ScoreRecords, ScoreRecord{
				ID:            asString(m["id"]),
				Score:         asFloat(m["score"]),
				Sci:           asFloat(m["sci"]),
				Se:            asFloat(m["se"]),
				Ssafe:         asFloat(m["ssafe"]),
				Ssmi:          asFloat(m["ssmi"]),
				Status:        asInt(m["status"]),
				AlgorithmType: asString(m["algorithmType"]),
				StartWorktime: asString(m["startWorktime"]),
				EndWorktime:   asString(m["endWorktime"]),
				IsBest:        asBool(m["isBest"]),
			})
		}
	}
	if arr, ok := data["files"].([]any); ok {
		for _, raw := range arr {
			m, ok := raw.(map[string]any)
			if !ok {
				continue
			}
			d.Files = append(d.Files, FileRecord{
				ID:         asString(m["id"]),
				FileName:   asString(m["fileName"]),
				UploadTime: asString(m["uploadTime"]),
				Score:      asFloat(m["score"]),
			})
		}
	}
	return d, nil
}

// ParseCleanup 解析 cleanup-tenant 统一响应体，data 为清理数量统计。
func ParseCleanup(res map[string]any) CleanupResult {
	code, _ := res["code"].(float64)
	if code != 200 {
		msg, _ := res["message"].(string)
		return CleanupResult{Error: fmt.Sprintf("cleanup api failed: code=%v message=%s", res["code"], msg)}
	}
	counts := map[string]int{}
	if data, ok := res["data"].(map[string]any); ok {
		for k, v := range data {
			if f, ok := v.(float64); ok {
				counts[k] = int(f)
			}
		}
	}
	return CleanupResult{Success: true, Counts: counts}
}

func asFloat(v any) *float64 {
	f, ok := v.(float64)
	if !ok {
		return nil
	}
	return &f
}

func asString(v any) string {
	s, _ := v.(string)
	return s
}

func asInt(v any) int {
	f, ok := v.(float64)
	if !ok {
		return 0
	}
	return int(f)
}

func asBool(v any) bool {
	b, _ := v.(bool)
	return b
}
