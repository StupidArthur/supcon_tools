package api

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

type Client struct {
	baseURL    string
	httpClient *http.Client
}

type StatusResponse struct {
	InstanceName       string  `json:"instance_name"`
	Mode               string  `json:"mode"`
	CycleCount         int     `json:"cycle_count"`
	SimTime            float64 `json:"sim_time"`
	SafeState          bool    `json:"safe_state"`
	ConsecutiveFailures int    `json:"consecutive_failures"`
}

type MetaResponse struct {
	InstanceName string                 `json:"instance_name"`
	Meta         map[string]interface{} `json:"meta"`
	Statistics   map[string]interface{} `json:"statistics"`
}

type SnapshotResponse map[string]float64

type ParamUpdateRequest struct {
	Param string  `json:"param"`
	Value float64 `json:"value"`
}

type OverrideRequest struct {
	Tag   string  `json:"tag"`
	Value float64 `json:"value"`
}

type ExportRequest struct {
	Path   string `json:"path"`
	Cycles *int   `json:"cycles,omitempty"`
}

type ExportResponse struct {
	Ok      bool   `json:"ok"`
	Path    string `json:"path"`
	Rows    int    `json:"rows"`
	Columns int    `json:"columns"`
}

func NewClient(baseURL string) *Client {
	if baseURL == "" {
		baseURL = "http://127.0.0.1:8000"
	}
	return &Client{
		baseURL:    baseURL,
		httpClient: &http.Client{Timeout: 10 * time.Second},
	}
}

func (c *Client) GetStatus() (*StatusResponse, error) {
	var resp StatusResponse
	if err := c.get("/api/status", &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

func (c *Client) GetMeta(name string) (*MetaResponse, error) {
	var resp MetaResponse
	if err := c.get(fmt.Sprintf("/api/instances/%s/meta", name), &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

func (c *Client) GetSnapshot(name string) (SnapshotResponse, error) {
	var resp SnapshotResponse
	if err := c.get(fmt.Sprintf("/api/instances/%s/snapshot", name), &resp); err != nil {
		return nil, err
	}
	return resp, nil
}

func (c *Client) SetParam(name, param string, value float64) error {
	req := ParamUpdateRequest{Param: param, Value: value}
	return c.post(fmt.Sprintf("/api/instances/%s/params", name), req, nil)
}

func (c *Client) Override(name, tag string, value float64) error {
	req := OverrideRequest{Tag: tag, Value: value}
	return c.post(fmt.Sprintf("/api/instances/%s/override", name), req, nil)
}

func (c *Client) Export(name, path string, cycles *int) (*ExportResponse, error) {
	req := ExportRequest{Path: path, Cycles: cycles}
	var resp ExportResponse
	if err := c.post(fmt.Sprintf("/api/instances/%s/export", name), req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

func (c *Client) get(path string, out interface{}) error {
	url := c.baseURL + path
	resp, err := c.httpClient.Get(url)
	if err != nil {
		return fmt.Errorf("GET %s: %w", url, err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("read response: %w", err)
	}
	if resp.StatusCode >= 400 {
		return fmt.Errorf("GET %s: status=%d body=%s", url, resp.StatusCode, string(body))
	}
	return json.Unmarshal(body, out)
}

func (c *Client) post(path string, reqBody, out interface{}) error {
	url := c.baseURL + path
	var buf bytes.Buffer
	if err := json.NewEncoder(&buf).Encode(reqBody); err != nil {
		return fmt.Errorf("encode request: %w", err)
	}
	resp, err := c.httpClient.Post(url, "application/json", &buf)
	if err != nil {
		return fmt.Errorf("POST %s: %w", url, err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("read response: %w", err)
	}
	if resp.StatusCode >= 400 {
		return fmt.Errorf("POST %s: status=%d body=%s", url, resp.StatusCode, string(body))
	}
	if out != nil {
		return json.Unmarshal(body, out)
	}
	return nil
}
