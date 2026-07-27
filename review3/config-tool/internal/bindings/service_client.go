package bindings

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"time"
)

// DataFactoryServiceClient 是访问常驻 DataFactoryService 的统一客户端（todo.md §5.2）。
//
// 所有请求统一：
//   - 拼接 http://127.0.0.1:<动态端口>
//   - 设置 Authorization: Bearer <token>
//   - 设置 Content-Type: application/json
//   - 限制响应体大小
//   - 检查 HTTP 状态码
//   - 解析 FastAPI detail
//   - 转换成清晰的 Go 错误
//   - 不在错误中打印 Token
type DataFactoryServiceClient struct {
	baseURL    string
	token      string
	httpClient *http.Client
}

// directProxy 直连，不走任何环境变量代理。
//
// http.Transport.Proxy 字段是 func(*http.Request) (*url.URL, error)：
//   - nil 会让 Transport 调用 ProxyFromEnvironment，读取 HTTP_PROXY /
//     HTTPS_PROXY / NO_PROXY，仍然可能把 127.0.0.1 路由到外部代理。
//   - 返回 (nil, nil) 是 Go 标准库明确约定的"直连"信号，所有请求
//     走 DialContext，不会触达任何代理。
func directProxy(*http.Request) (*url.URL, error) { return nil, nil }

// NewDataFactoryServiceClient 创建服务客户端。
func NewDataFactoryServiceClient(host string, port int, token string) *DataFactoryServiceClient {
	return &DataFactoryServiceClient{
		baseURL: fmt.Sprintf("http://%s:%d", host, port),
		token:   token,
		// 禁用代理：127.0.0.1 上的 service 不应被环境变量 HTTP_PROXY / HTTPS_PROXY
		// / NO_PROXY 路由到外部代理。在配置了系统代理的生产机上，之前用
		// Proxy: nil 仍会触发 ProxyFromEnvironment，CheckHealth 1s 内
		// 全部超时；这里改用返回 (nil, nil) 的闭包强制直连。
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
			Transport: &http.Transport{
				Proxy: directProxy,
			},
		},
	}
}

// ServiceError 是服务返回的结构化错误。
type ServiceError struct {
	StatusCode int
	Detail     string
	Path       string
}

func (e *ServiceError) Error() string {
	if e.Detail != "" {
		return fmt.Sprintf("服务请求失败 [%s] HTTP %d: %s", e.Path, e.StatusCode, e.Detail)
	}
	return fmt.Sprintf("服务请求失败 [%s] HTTP %d", e.Path, e.StatusCode)
}

// DoJSON 发送 JSON 请求并解析响应（todo.md §5.2）。
//
// request 为 nil 时不发送 body（GET 请求）。
// response 为 nil 时不解析响应体。
func (c *DataFactoryServiceClient) DoJSON(ctx context.Context, method, path string, request any, response any) error {
	url := c.baseURL + path

	var bodyReader io.Reader
	if request != nil {
		data, err := json.Marshal(request)
		if err != nil {
			return fmt.Errorf("序列化请求失败 [%s]: %w", path, err)
		}
		bodyReader = bytes.NewReader(data)
	}

	req, err := http.NewRequestWithContext(ctx, method, url, bodyReader)
	if err != nil {
		return fmt.Errorf("创建请求失败 [%s]: %w", path, err)
	}
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	if request != nil {
		req.Header.Set("Content-Type", "application/json")
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("服务连接失败 [%s]: %w", path, err)
	}
	defer resp.Body.Close()

	// 限制响应体大小：读取 maxBytes+1，超过 maxBytes 则报错。
	// 避免截断后的 JSON 被误报为解析失败。
	const maxBytes int64 = 10 * 1024 * 1024
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxBytes+1))
	if err != nil {
		return fmt.Errorf("读取响应失败 [%s]: %w", path, err)
	}
	if int64(len(body)) > maxBytes {
		return fmt.Errorf("服务响应超过限制 [%s]: >%d bytes", path, maxBytes)
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		detail := parseFastAPIDetail(body)
		return &ServiceError{
			StatusCode: resp.StatusCode,
			Detail:     detail,
			Path:       path,
		}
	}

	if response != nil && len(body) > 0 {
		if err := json.Unmarshal(body, response); err != nil {
			return fmt.Errorf("解析响应失败 [%s]: %w", path, err)
		}
	}
	return nil
}

// parseFastAPIDetail 从 FastAPI 错误响应中提取 detail 字段。
func parseFastAPIDetail(body []byte) string {
	var errResp struct {
		Detail string `json:"detail"`
	}
	if json.Unmarshal(body, &errResp) == nil && errResp.Detail != "" {
		return errResp.Detail
	}
	// 非 JSON 或无 detail 时返回原始 body 前 200 字符
	s := string(body)
	if len(s) > 200 {
		s = s[:200]
	}
	return s
}

// HealthResponse 是 /api/health 的响应结构（todo.md §5.3）。
type HealthResponse struct {
	OK              bool   `json:"ok"`
	ProtocolVersion int    `json:"protocolVersion"`
	ServiceState    string `json:"serviceState"`
	RuntimeState    string `json:"runtimeState"`
	InstanceName    string `json:"instanceName"`
}

// CheckHealth 校验服务健康状态（todo.md §5.3）。
// 必须校验 ok=true, protocolVersion=1, serviceState=ready。
func (c *DataFactoryServiceClient) CheckHealth(ctx context.Context) (*HealthResponse, error) {
	var resp HealthResponse
	if err := c.DoJSON(ctx, "GET", "/api/health", nil, &resp); err != nil {
		return nil, err
	}
	if !resp.OK {
		return nil, fmt.Errorf("服务 health 返回 ok=false")
	}
	if resp.ProtocolVersion != ServiceProtocolVersion {
		return nil, fmt.Errorf(
			"DataFactoryService 协议版本不匹配：Config Tool 需要 %d，服务返回 %d",
			ServiceProtocolVersion, resp.ProtocolVersion,
		)
	}
	if resp.ServiceState != "ready" {
		return nil, fmt.Errorf("服务状态不是 ready：当前 %s", resp.ServiceState)
	}
	return &resp, nil
}

// ServiceProtocolVersion 是 Config Tool 期望的服务协议版本。
const ServiceProtocolVersion = 1
