package batch

import "testing"

func TestParseEvalConfig(t *testing.T) {
	res := map[string]any{
		"code": float64(200),
		"data": map[string]any{
			"id": float64(1), "pracLoadEnabled": float64(1), "examLoadEnabled": float64(0),
			"evalDurationMinutes": float64(120),
			"addTime":             "2026-08-01 10:00:00", "updateTime": "2026-08-06 12:00:00",
		},
	}
	cfg, err := ParseEvalConfig(res)
	if err != nil {
		t.Fatalf("应成功，得到错误: %v", err)
	}
	if cfg.PracLoadEnabled != 1 || cfg.ExamLoadEnabled != 0 || cfg.EvalDurationMinutes != 120 {
		t.Errorf("字段解析错误: %+v", cfg)
	}
	if cfg.UpdateTime != "2026-08-06 12:00:00" {
		t.Errorf("updateTime 解析错误: %q", cfg.UpdateTime)
	}
}

func TestParseEvalConfigError(t *testing.T) {
	res := map[string]any{"code": float64(500), "message": "boom"}
	if _, err := ParseEvalConfig(res); err == nil {
		t.Fatal("code 非 200 应返回错误")
	}
}

func TestParseEvalConfigEmpty(t *testing.T) {
	res := map[string]any{"code": float64(200)}
	cfg, err := ParseEvalConfig(res)
	if err != nil {
		t.Fatalf("应成功，得到错误: %v", err)
	}
	if cfg.PracLoadEnabled != 0 || cfg.EvalDurationMinutes != 0 {
		t.Errorf("data 缺失应返回零值配置: %+v", cfg)
	}
}

func TestParseUpdate(t *testing.T) {
	if r := ParseUpdate(map[string]any{"code": float64(200)}); !r.Success || r.Error != "" {
		t.Errorf("code=200 应成功: %+v", r)
	}
	if r := ParseUpdate(map[string]any{"code": float64(400), "message": "bad"}); r.Success || r.Error == "" {
		t.Errorf("code 非 200 应失败: %+v", r)
	}
}
