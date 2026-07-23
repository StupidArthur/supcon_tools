package realtime

import (
	"strings"
	"testing"
)

func TestErrorCodesDefined(t *testing.T) {
	codes := []string{
		ErrProjectNotFound, ErrCompileFailed, ErrStartFailed, ErrSessionConflict,
		ErrSessionNotRunning, ErrTagNotFound, ErrForceInvalid, ErrAlarmInvalid,
		ErrDashboardInvalid, ErrAPIUnavailable,
	}
	for _, c := range codes {
		if !strings.HasPrefix(c, "REALTIME_") {
			t.Fatalf("error code should be prefixed REALTIME_: %s", c)
		}
	}
}

func TestRealtimeErrorFormat(t *testing.T) {
	e := NewError(ErrProjectNotFound, "工程不存在")
	if e.Code != ErrProjectNotFound {
		t.Fatalf("unexpected code: %s", e.Code)
	}
	if !strings.Contains(e.Error(), "REALTIME_PROJECT_NOT_FOUND") {
		t.Fatalf("Error() should contain code: %s", e.Error())
	}
}

func TestDuplicateErrorCode(t *testing.T) {
	e := NewDuplicateError(ValidationResult{})
	if e.Code != ErrDuplicateNames {
		t.Fatalf("unexpected code: %s", e.Code)
	}
}
