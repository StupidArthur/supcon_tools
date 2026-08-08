package ranking

import "testing"

func TestParseRanking(t *testing.T) {
	res := map[string]any{
		"code":    float64(200),
		"message": "success",
		"data": []any{
			map[string]any{"tenantId": "BBB", "controlScore": 80.5, "softSensorScore": 90.0, "totalScore": 82.4, "rank": float64(2)},
			map[string]any{"tenantId": "AAA", "controlScore": 95.5, "softSensorScore": nil, "totalScore": 76.4, "rank": float64(1)},
			map[string]any{"tenantId": "CCC", "controlScore": nil, "softSensorScore": nil, "totalScore": 0.0, "rank": float64(3)},
		},
	}
	items, err := ParseRanking(res)
	if err != nil {
		t.Fatalf("应成功，得到错误: %v", err)
	}
	if len(items) != 3 {
		t.Fatalf("应返回 3 条，得到 %d", len(items))
	}
	if items[0].TenantID != "AAA" || items[1].TenantID != "BBB" || items[2].TenantID != "CCC" {
		t.Errorf("应按 rank 升序排列，得到 %v", items)
	}
	if items[0].SoftSensorScore != nil {
		t.Errorf("AAA 软测量应为 nil，得到 %v", *items[0].SoftSensorScore)
	}
	if items[1].ControlScore == nil || *items[1].ControlScore != 80.5 {
		t.Errorf("BBB 控制最优应为 80.5，得到 %v", items[1].ControlScore)
	}
	if items[2].Rank != 3 || items[2].TotalScore != 0 {
		t.Errorf("CCC 应为 rank=3 total=0，得到 %+v", items[2])
	}
}

func TestParseRankingSameRank(t *testing.T) {
	res := map[string]any{
		"code": float64(200),
		"data": []any{
			map[string]any{"tenantId": "LOW", "totalScore": 60.0, "rank": float64(1)},
			map[string]any{"tenantId": "HIGH", "totalScore": 90.0, "rank": float64(1)},
		},
	}
	items, err := ParseRanking(res)
	if err != nil {
		t.Fatalf("应成功，得到错误: %v", err)
	}
	if items[0].TenantID != "HIGH" {
		t.Errorf("同分应按总分降序，得到 %v", items[0].TenantID)
	}
}

func TestParseRankingError(t *testing.T) {
	res := map[string]any{"code": float64(500), "message": "internal error"}
	if _, err := ParseRanking(res); err == nil {
		t.Fatal("code 非 200 应返回错误")
	}
}

func TestParseRankingEmpty(t *testing.T) {
	res := map[string]any{"code": float64(200)}
	items, err := ParseRanking(res)
	if err != nil {
		t.Fatalf("应成功，得到错误: %v", err)
	}
	if len(items) != 0 {
		t.Errorf("应返回空列表，得到 %d 条", len(items))
	}
}

func TestAttachNames(t *testing.T) {
	items := []Item{{TenantID: "AAA"}, {TenantID: "UNKNOWN"}}
	AttachNames(items, map[string]string{"AAA": "夜雨生烦"})
	if items[0].Name != "夜雨生烦" {
		t.Errorf("AAA 应关联队伍名，得到 %q", items[0].Name)
	}
	if items[1].Name != "" {
		t.Errorf("未知租户应保持空名，得到 %q", items[1].Name)
	}
}
