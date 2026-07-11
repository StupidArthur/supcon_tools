package bindings

import (
	"context"
	"encoding/json"
	"log"
	"sort"
	"sync"

	"pid_debug_gui/internal/api"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

type DebugBinding struct {
	ctx       context.Context
	apiClient *api.Client
	wsClient  *api.WsClient
	mu        sync.RWMutex

	connected       bool
	instanceName    string
	lastSnapshot    map[string]float64
	snapshotHistory []map[string]float64
	maxHistory      int
}

func NewDebugBinding() *DebugBinding {
	return &DebugBinding{
		maxHistory: 10000,
	}
}

func (d *DebugBinding) Startup(ctx context.Context) {
	d.ctx = ctx
}

func (d *DebugBinding) Shutdown(_ context.Context) {
	if d.wsClient != nil {
		d.wsClient.Disconnect()
	}
}

func (d *DebugBinding) Connect(baseURL string) (string, error) {
	if baseURL == "" {
		baseURL = "http://127.0.0.1:8000"
	}

	d.mu.Lock()
	defer d.mu.Unlock()

	client := api.NewClient(baseURL)
	status, err := client.GetStatus()
	if err != nil {
		return "", err
	}

	d.instanceName = status.InstanceName
	d.apiClient = client

	wsClient := api.NewWsClient(baseURL)
	wsClient.SetOnSnapshot(func(snap map[string]float64) {
		d.mu.Lock()
		d.lastSnapshot = snap
		d.snapshotHistory = append(d.snapshotHistory, snap)
		if len(d.snapshotHistory) > d.maxHistory {
			d.snapshotHistory = d.snapshotHistory[d.maxHistory/4:]
		}
		d.mu.Unlock()
		runtime.EventsEmit(d.ctx, "snapshot", snap)
	})

	if err := wsClient.Connect(); err != nil {
		return "", err
	}
	d.wsClient = wsClient
	d.connected = true

	log.Printf("Connected to %s, instance=%s", baseURL, d.instanceName)
	return d.instanceName, nil
}

func (d *DebugBinding) Disconnect() {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.wsClient != nil {
		d.wsClient.Disconnect()
	}
	d.connected = false
	d.lastSnapshot = nil
}

func (d *DebugBinding) IsConnected() bool {
	d.mu.RLock()
	defer d.mu.RUnlock()
	return d.connected
}

func (d *DebugBinding) GetStatus() (string, error) {
	if d.apiClient == nil {
		return "", nil
	}
	status, err := d.apiClient.GetStatus()
	if err != nil {
		return "", err
	}
	b, _ := json.Marshal(status)
	return string(b), nil
}

func (d *DebugBinding) GetMeta() (string, error) {
	d.mu.RLock()
	name := d.instanceName
	d.mu.RUnlock()
	if d.apiClient == nil || name == "" {
		return "{}", nil
	}
	meta, err := d.apiClient.GetMeta(name)
	if err != nil {
		return "", err
	}
	b, _ := json.Marshal(meta)
	return string(b), nil
}

func (d *DebugBinding) SetParam(name, param string, value float64) error {
	if d.apiClient == nil {
		return nil
	}
	return d.apiClient.SetParam(name, param, value)
}

func (d *DebugBinding) Override(tag string, value float64) error {
	d.mu.RLock()
	name := d.instanceName
	d.mu.RUnlock()
	if d.apiClient == nil || name == "" {
		return nil
	}
	return d.apiClient.Override(name, tag, value)
}

func (d *DebugBinding) ExportCsv(path string) (string, error) {
	d.mu.RLock()
	name := d.instanceName
	d.mu.RUnlock()
	if d.apiClient == nil || name == "" {
		return "", nil
	}
	resp, err := d.apiClient.Export(name, path, nil)
	if err != nil {
		return "", err
	}
	b, _ := json.Marshal(resp)
	return string(b), nil
}

func (d *DebugBinding) GetLastSnapshot() (string, error) {
	d.mu.RLock()
	defer d.mu.RUnlock()
	if d.lastSnapshot == nil {
		return "{}", nil
	}
	b, _ := json.Marshal(d.lastSnapshot)
	return string(b), nil
}

func (d *DebugBinding) GetSnapshotHistory() (string, error) {
	d.mu.RLock()
	defer d.mu.RUnlock()
	n := len(d.snapshotHistory)
	if n == 0 {
		return "[]", nil
	}
	limit := 2000
	start := 0
	if n > limit {
		start = n - limit
	}
	b, _ := json.Marshal(d.snapshotHistory[start:])
	return string(b), nil
}

func (d *DebugBinding) GetDisplayVariables() (string, error) {
	metaStr, err := d.GetMeta()
	if err != nil {
		return "[]", err
	}
	var meta api.MetaResponse
	if err := json.Unmarshal([]byte(metaStr), &meta); err != nil {
		return "[]", nil
	}

	type varInfo struct {
		Name  string  `json:"name"`
		Scale float64 `json:"scale"`
	}
	var vars []varInfo
	for key, info := range meta.Meta {
		m, ok := info.(map[string]interface{})
		if !ok {
			continue
		}
		isDisp, _ := m["is_display"].(bool)
		if !isDisp {
			continue
		}
		scale := 100.0
		if s, ok := m["plot_scale_ref"].(float64); ok && s > 0 {
			scale = s
		}
		vars = append(vars, varInfo{Name: key, Scale: scale})
	}

	sort.Slice(vars, func(i, j int) bool { return vars[i].Name < vars[j].Name })
	b, _ := json.Marshal(vars)
	return string(b), nil
}
