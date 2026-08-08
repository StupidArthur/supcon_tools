package monitor

import "testing"

func TestParseQualitiesAllGood(t *testing.T) {
	res := map[string]any{
		"code": float64(200),
		"data": []any{
			map[string]any{"name": "A.PV", "quality": float64(192)},
			map[string]any{"name": "B.SV", "quality": float64(192)},
		},
	}
	total, good, bad, err := ParseQualities(res)
	if err != nil {
		t.Fatalf("应成功，得到错误: %v", err)
	}
	if total != 2 || good != 2 || len(bad) != 0 {
		t.Errorf("应 total=2 good=2 bad=0，得到 %d/%d/%v", total, good, bad)
	}
}

func TestParseQualitiesMixed(t *testing.T) {
	res := map[string]any{
		"code": float64(200),
		"data": []any{
			map[string]any{"name": "A.PV", "quality": float64(192)},
			map[string]any{"name": "B.SV", "quality": float64(0)},
			map[string]any{"name": "C.MV", "quality": float64(24)},
		},
	}
	total, good, bad, err := ParseQualities(res)
	if err != nil {
		t.Fatalf("应成功，得到错误: %v", err)
	}
	if total != 3 || good != 1 || len(bad) != 2 {
		t.Errorf("应 total=3 good=1 bad=2，得到 %d/%d/%v", total, good, bad)
	}
	if bad[0] != "B.SV" || bad[1] != "C.MV" {
		t.Errorf("bad 列表应为 [B.SV C.MV]，得到 %v", bad)
	}
}

func TestParseQualitiesError(t *testing.T) {
	res := map[string]any{"code": float64(500), "message": "boom"}
	if _, _, _, err := ParseQualities(res); err == nil {
		t.Fatal("code 非 200 应返回错误")
	}
}

func TestParseQualitiesEmpty(t *testing.T) {
	total, good, bad, err := ParseQualities(map[string]any{"code": float64(200)})
	if err != nil {
		t.Fatalf("应成功，得到错误: %v", err)
	}
	if total != 0 || good != 0 || bad == nil {
		t.Errorf("应为空且 bad 非 nil: %d/%d/%v", total, good, bad)
	}
}
