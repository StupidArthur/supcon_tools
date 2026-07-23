package realtime

import (
	"context"
	"os"
	"testing"
)

func validAlarmRule() AlarmRule {
	return AlarmRule{
		Name:         "水位高高",
		Tag:          "tank.level",
		Direction:    DirectionHigh,
		Limit:        1.1,
		Severity:     SeverityCritical,
		DelaySeconds: 2,
		Deadband:     0.02,
		Enabled:      true,
		Message:      "液位超过高高限",
	}
}

func TestAlarmCRUD(t *testing.T) {
	m := newTestManager(t, &fakeCompiler{result: validResult()})
	ctx := context.Background()
	p, _ := m.CreateProject(ctx, "proj")

	rules, err := m.CreateAlarmRule(ctx, p.ID, validAlarmRule())
	if err != nil {
		t.Fatal(err)
	}
	if len(rules) != 1 {
		t.Fatalf("expected 1 rule, got %d", len(rules))
	}
	if rules[0].ID == "" {
		t.Fatal("expected generated ID")
	}

	listed, _ := m.ListAlarmRules(ctx, p.ID)
	if len(listed) != 1 {
		t.Fatalf("expected 1 listed, got %d", len(listed))
	}

	// update
	upd := listed[0]
	upd.Limit = 1.5
	updated, err := m.UpdateAlarmRule(ctx, p.ID, upd)
	if err != nil {
		t.Fatal(err)
	}
	if updated[0].Limit != 1.5 {
		t.Fatalf("expected limit 1.5, got %f", updated[0].Limit)
	}

	// delete
	deleted, err := m.DeleteAlarmRule(ctx, p.ID, upd.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(deleted) != 0 {
		t.Fatalf("expected 0 after delete, got %d", len(deleted))
	}
}

func TestAlarmValidation(t *testing.T) {
	cases := []struct {
		name    string
		mutate  func(*AlarmRule)
		wantErr bool
	}{
		{"valid", func(r *AlarmRule) {}, false},
		{"empty name", func(r *AlarmRule) { r.Name = "" }, true},
		{"empty tag", func(r *AlarmRule) { r.Tag = "" }, true},
		{"bad direction", func(r *AlarmRule) { r.Direction = "up" }, true},
		{"bad severity", func(r *AlarmRule) { r.Severity = "fatal" }, true},
		{"negative deadband", func(r *AlarmRule) { r.Deadband = -1 }, true},
		{"negative delay", func(r *AlarmRule) { r.DelaySeconds = -1 }, true},
		{"nan limit", func(r *AlarmRule) { r.Limit = nan() }, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := validAlarmRule()
			c.mutate(&r)
			err := ValidateAlarmRule(r)
			if c.wantErr && err == nil {
				t.Fatal("expected error")
			}
			if !c.wantErr && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
		})
	}
}

func nan() float64 {
	var z float64
	return z / z
}

func TestAlarmDuplicateIDRejected(t *testing.T) {
	m := newTestManager(t, &fakeCompiler{result: validResult()})
	ctx := context.Background()
	p, _ := m.CreateProject(ctx, "proj")

	r := validAlarmRule()
	r.ID = "fixed-id"
	if _, err := m.CreateAlarmRule(ctx, p.ID, r); err != nil {
		t.Fatal(err)
	}
	if _, err := m.CreateAlarmRule(ctx, p.ID, r); err == nil {
		t.Fatal("expected duplicate ID error")
	}
}

func TestAlarmRevisionChanges(t *testing.T) {
	m := newTestManager(t, &fakeCompiler{result: validResult()})
	ctx := context.Background()
	p, _ := m.CreateProject(ctx, "proj")

	before, _ := m.RuntimeRevision(p.ID)
	if _, err := m.CreateAlarmRule(ctx, p.ID, validAlarmRule()); err != nil {
		t.Fatal(err)
	}
	after, _ := m.RuntimeRevision(p.ID)
	if before == after {
		t.Fatal("revision should change when alarm rules change")
	}
}

func TestAlarmAtomicSave(t *testing.T) {
	m := newTestManager(t, &fakeCompiler{result: validResult()})
	ctx := context.Background()
	p, _ := m.CreateProject(ctx, "proj")
	if _, err := m.CreateAlarmRule(ctx, p.ID, validAlarmRule()); err != nil {
		t.Fatal(err)
	}
	// tmp 文件不应残留
	tmp := m.storage.alarmsFilePath(p.ID) + ".tmp"
	if fileExists(tmp) {
		t.Fatal("tmp file should not remain")
	}
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
