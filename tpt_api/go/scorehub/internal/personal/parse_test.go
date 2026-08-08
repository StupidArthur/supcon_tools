package personal

import "testing"

func TestParseDetail(t *testing.T) {
	res := map[string]any{
		"code": float64(200),
		"data": map[string]any{
			"tenantId": "AQW7K69J",
			"scoreRecords": []any{
				map[string]any{
					"id": "r1", "score": 96.494, "sci": 90.1, "status": float64(2),
					"algorithmType": "v2", "isBest": true,
					"startWorktime": "2026-08-01 10:00:00", "endWorktime": "2026-08-01 12:00:00",
				},
				map[string]any{"id": "r2", "score": nil, "status": float64(1)},
			},
			"files": []any{
				map[string]any{"id": "f1", "fileName": "predict.xlsx", "uploadTime": "2026-08-02 09:00:00", "score": 82.47},
			},
		},
	}
	d, err := ParseDetail(res)
	if err != nil {
		t.Fatalf("应成功，得到错误: %v", err)
	}
	if d.TenantID != "AQW7K69J" {
		t.Errorf("tenantId 解析错误: %q", d.TenantID)
	}
	if len(d.ScoreRecords) != 2 {
		t.Fatalf("应有 2 条成绩记录，得到 %d", len(d.ScoreRecords))
	}
	r1 := d.ScoreRecords[0]
	if r1.Score == nil || *r1.Score != 96.494 || r1.Status != 2 || !r1.IsBest {
		t.Errorf("r1 解析错误: %+v", r1)
	}
	if d.ScoreRecords[1].Score != nil {
		t.Errorf("评估中记录 score 应为 nil: %+v", d.ScoreRecords[1])
	}
	if len(d.Files) != 1 || d.Files[0].FileName != "predict.xlsx" || *d.Files[0].Score != 82.47 {
		t.Errorf("files 解析错误: %+v", d.Files)
	}
}

func TestParseDetailError(t *testing.T) {
	res := map[string]any{"code": float64(403), "message": "no permission"}
	if _, err := ParseDetail(res); err == nil {
		t.Fatal("code 非 200 应返回错误")
	}
}

func TestParseDetailEmpty(t *testing.T) {
	res := map[string]any{"code": float64(200), "data": map[string]any{"tenantId": "X", "scoreRecords": []any{}, "files": []any{}}}
	d, err := ParseDetail(res)
	if err != nil {
		t.Fatalf("应成功，得到错误: %v", err)
	}
	if len(d.ScoreRecords) != 0 || len(d.Files) != 0 {
		t.Errorf("应为空列表: %+v", d)
	}
}

func TestParseCleanup(t *testing.T) {
	res := map[string]any{"code": float64(200), "data": map[string]any{"scoreRecords": float64(3), "files": float64(1)}}
	r := ParseCleanup(res)
	if !r.Success || r.Error != "" {
		t.Errorf("应成功: %+v", r)
	}
	if r.Counts["scoreRecords"] != 3 || r.Counts["files"] != 1 {
		t.Errorf("counts 解析错误: %+v", r.Counts)
	}
}

func TestParseCleanupError(t *testing.T) {
	res := map[string]any{"code": float64(500), "message": "boom"}
	r := ParseCleanup(res)
	if r.Success || r.Error == "" {
		t.Errorf("code 非 200 应失败: %+v", r)
	}
}
