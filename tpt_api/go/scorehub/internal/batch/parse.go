package batch

import "fmt"

// ParseEvalConfig 解析 eval-config GET 统一响应体 {code, message, data}。
// data 为配置对象，含 id/pracLoadEnabled/examLoadEnabled/evalDurationMinutes/addTime/updateTime。
func ParseEvalConfig(res map[string]any) (*EvalConfig, error) {
	code, _ := res["code"].(float64)
	if code != 200 {
		msg, _ := res["message"].(string)
		return nil, fmt.Errorf("eval-config api failed: code=%v message=%s", res["code"], msg)
	}
	cfg := &EvalConfig{}
	data, ok := res["data"].(map[string]any)
	if !ok {
		return cfg, nil
	}
	cfg.ID = asInt(data["id"])
	cfg.PracLoadEnabled = asInt(data["pracLoadEnabled"])
	cfg.ExamLoadEnabled = asInt(data["examLoadEnabled"])
	cfg.EvalDurationMinutes = asInt(data["evalDurationMinutes"])
	cfg.StartWorktimeDelayMinutes = asInt(data["startWorktimeDelayMinutes"])
	cfg.AddTime = asString(data["addTime"])
	cfg.UpdateTime = asString(data["updateTime"])
	return cfg, nil
}

// ParseUpdate 解析 eval-config POST 统一响应体，code=200 即成功。
func ParseUpdate(res map[string]any) UpdateResult {
	code, _ := res["code"].(float64)
	if code != 200 {
		msg, _ := res["message"].(string)
		return UpdateResult{Error: fmt.Sprintf("update eval-config failed: code=%v message=%s", res["code"], msg)}
	}
	return UpdateResult{Success: true}
}

func asInt(v any) int {
	f, ok := v.(float64)
	if !ok {
		return 0
	}
	return int(f)
}

func asString(v any) string {
	s, _ := v.(string)
	return s
}
