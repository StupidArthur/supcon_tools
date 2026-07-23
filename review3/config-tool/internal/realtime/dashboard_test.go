package realtime

import (
	"context"
	"testing"
)

func validDashboard() Dashboard {
	return Dashboard{
		Version: 1,
		Pages: []DashboardPage{
			{
				ID:   "main",
				Name: "主画面",
				Widgets: []DashboardWidget{
					{ID: "w1", Type: "value", Tag: "tank.level", X: 0, Y: 0, W: 3, H: 2, Options: map[string]any{"title": "液位"}},
				},
			},
		},
	}
}

func TestDashboardRoundTrip(t *testing.T) {
	m := newTestManager(t, &fakeCompiler{result: validResult()})
	ctx := context.Background()
	p, _ := m.CreateProject(ctx, "proj")

	saved, err := m.SaveDashboard(ctx, p.ID, validDashboard())
	if err != nil {
		t.Fatal(err)
	}
	if len(saved.Pages) != 1 {
		t.Fatalf("expected 1 page, got %d", len(saved.Pages))
	}

	loaded, err := m.GetDashboard(ctx, p.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(loaded.Pages) != 1 || loaded.Pages[0].Widgets[0].Tag != "tank.level" {
		t.Fatalf("round trip mismatch: %+v", loaded)
	}
}

func TestDashboardValidation(t *testing.T) {
	cases := []struct {
		name    string
		mutate  func(*Dashboard)
		wantErr bool
	}{
		{"valid", func(d *Dashboard) {}, false},
		{"empty page id", func(d *Dashboard) { d.Pages[0].ID = "" }, true},
		{"dup page id", func(d *Dashboard) {
			d.Pages = append(d.Pages, DashboardPage{ID: "main", Name: "x"})
		}, true},
		{"bad widget type", func(d *Dashboard) { d.Pages[0].Widgets[0].Type = "chart" }, true},
		{"zero size", func(d *Dashboard) { d.Pages[0].Widgets[0].W = 0 }, true},
		{"dup widget id", func(d *Dashboard) {
			d.Pages[0].Widgets = append(d.Pages[0].Widgets, DashboardWidget{ID: "w1", Type: "text", W: 1, H: 1})
		}, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			d := validDashboard()
			c.mutate(&d)
			err := ValidateDashboard(d)
			if c.wantErr && err == nil {
				t.Fatal("expected error")
			}
			if !c.wantErr && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
		})
	}
}

func TestDashboardEmptyWhenMissing(t *testing.T) {
	m := newTestManager(t, &fakeCompiler{result: validResult()})
	ctx := context.Background()
	p, _ := m.CreateProject(ctx, "proj")
	d, err := m.GetDashboard(ctx, p.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(d.Pages) != 0 {
		t.Fatalf("expected empty dashboard, got %d pages", len(d.Pages))
	}
}

func TestDashboardNotInRevision(t *testing.T) {
	m := newTestManager(t, &fakeCompiler{result: validResult()})
	ctx := context.Background()
	p, _ := m.CreateProject(ctx, "proj")
	before, _ := m.RuntimeRevision(p.ID)
	if _, err := m.SaveDashboard(ctx, p.ID, validDashboard()); err != nil {
		t.Fatal(err)
	}
	after, _ := m.RuntimeRevision(p.ID)
	if before != after {
		t.Fatal("dashboard change should NOT affect runtime revision")
	}
}
