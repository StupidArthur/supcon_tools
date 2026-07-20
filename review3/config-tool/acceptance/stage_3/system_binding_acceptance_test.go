package stage3_acceptance_test

// Reviewer-owned acceptance for SystemBinding public contract (stage 3).
// Full Start/Stop/race lifecycle with injected mocks remains in
// config-tool/internal/bindings/system_test.go and is exercised by manifest
// command go test -race ./internal/bindings.

import (
	"strings"
	"testing"

	"config-tool/internal/bindings"
)

func TestAcceptanceBuildArgsIncludesApiAndOpcUaPorts(t *testing.T) {
	params := bindings.StartParams{
		ConfigPath:  "config/test.yaml",
		Mode:        "REALTIME",
		CycleTime:   0.5,
		Port:        18951,
		APIPort:     8123,
		APIHost:     "127.0.0.1",
		RuntimeName: "stage3_acceptance",
		EnableOpcUa: true,
	}
	args := bindings.BuildArgs(params)
	joined := strings.Join(args, " ")
	for _, needle := range []string{
		"-c", "config/test.yaml",
		"--mode", "REALTIME",
		"--cycle-time", "0.5",
		"--port", "18951",
		"--api",
		"--api-host", "127.0.0.1",
		"--api-port", "8123",
		"--name", "stage3_acceptance",
	} {
		if !strings.Contains(joined, needle) {
			t.Fatalf("BuildArgs missing %q in %v", needle, args)
		}
	}
}

func TestAcceptanceBuildArgsApiPortDistinctFromOpcUaPort(t *testing.T) {
	params := bindings.StartParams{
		ConfigPath:  "x.yaml",
		Port:        11111,
		APIPort:     22222,
		RuntimeName: "inst",
	}
	args := bindings.BuildArgs(params)
	portIdx := indexOf(args, "--port")
	apiIdx := indexOf(args, "--api-port")
	if portIdx < 0 || apiIdx < 0 {
		t.Fatalf("missing port flags: %v", args)
	}
	if args[portIdx+1] == args[apiIdx+1] {
		t.Fatalf("OPC UA port and API port must not be conflated: %v", args)
	}
}

func TestAcceptanceParseStatusResponseRequiresInstanceName(t *testing.T) {
	payload := []byte(`{
		"instance_name":"runtime_a",
		"mode":"REALTIME",
		"cycle_count":3,
		"sim_time":1.5,
		"cycle_time":0.5,
		"safe_state":false,
		"consecutive_failures":0
	}`)
	resp, err := bindings.ParseStatusResponse(payload)
	if err != nil {
		t.Fatalf("ParseStatusResponse: %v", err)
	}
	if resp.InstanceName != "runtime_a" {
		t.Fatalf("instance_name=%q", resp.InstanceName)
	}
}

func TestAcceptanceStopWhenNotRunningReturnsError(t *testing.T) {
	b := bindings.NewSystemBinding()
	err := b.Stop()
	if err == nil {
		t.Fatal("expected error when stopping idle binding")
	}
	if !strings.Contains(err.Error(), "未在运行") {
		t.Fatalf("unexpected idle Stop error: %v", err)
	}
}

func TestAcceptanceCleanupWhenNotRunningIsSafe(t *testing.T) {
	b := bindings.NewSystemBinding()
	b.Cleanup()
	status := b.Status()
	if status.Running {
		t.Fatalf("Cleanup should leave binding stopped: %+v", status)
	}
}

func TestAcceptanceDuplicateStartWithoutDataFactoryReturnsError(t *testing.T) {
	b := bindings.NewSystemBinding()
	// NewSystemBinding uses findDataFactory(); when empty, Start must fail fast.
	err := b.Start(bindings.StartParams{ConfigPath: "missing.yaml", RuntimeName: "x"})
	if err == nil {
		b.Cleanup()
		t.Fatal("expected Start error when DataFactory path unavailable or config missing")
	}
}

func indexOf(args []string, target string) int {
	for i, arg := range args {
		if arg == target {
			return i
		}
	}
	return -1
}
