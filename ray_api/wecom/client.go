package wecom

// client.go: 企业微信群机器人 webhook 客户端 (同步, 内置超时 + 重试)。
// 与 Python 版 notifier/wecom/client.py 行为一致:
//   - 业务错误 (errcode != 0) 返回 *WeComError, 不重试
//   - 网络错误 / 非 200 指数退避重试 retries 次
// 仅依赖 Go 标准库。

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

const (
	WebhookURL     = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
	UploadURL      = "https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media"
	DefaultTimeout = 10 * time.Second
	DefaultRetries = 3
	DefaultBackoff = 500 * time.Millisecond // 指数退避基数: 0.5s, 1s, 2s, ...
)

// Client 企业微信群机器人客户端。
type Client struct {
	Key        string
	webhookURL string
	timeout    time.Duration
	retries    int
	backoff    time.Duration
	http       *http.Client
}

// Option 配置项。
type Option func(*Client)

func WithTimeout(d time.Duration) Option    { return func(c *Client) { c.timeout = d } }
func WithRetries(n int) Option              { return func(c *Client) { c.retries = n } }
func WithBackoff(d time.Duration) Option    { return func(c *Client) { c.backoff = d } }
func WithWebhookURL(u string) Option        { return func(c *Client) { c.webhookURL = u } }

// NewClient 创建客户端。key 为群机器人 webhook 的 key。
func NewClient(key string, opts ...Option) (*Client, error) {
	if key == "" {
		return nil, fmt.Errorf("wecom: key 不能为空")
	}
	c := &Client{
		Key:        key,
		webhookURL: WebhookURL,
		timeout:    DefaultTimeout,
		retries:    DefaultRetries,
		backoff:    DefaultBackoff,
	}
	for _, o := range opts {
		o(c)
	}
	c.http = &http.Client{Timeout: c.timeout}
	return c, nil
}

// FromEnv 从环境变量 WECOM_WEBHOOK_KEY 创建客户端。
func FromEnv(opts ...Option) (*Client, error) {
	key := os.Getenv("WECOM_WEBHOOK_KEY")
	if key == "" {
		return nil, fmt.Errorf("wecom: 环境变量 WECOM_WEBHOOK_KEY 未设置")
	}
	return NewClient(key, opts...)
}

// Close 释放底层连接。
func (c *Client) Close() { c.http.CloseIdleConnections() }

// do 执行请求, 返回响应体。网络错误或非 200 返回 error。
func (c *Client) do(ctx context.Context, req *http.Request) ([]byte, error) {
	resp, err := c.http.Do(req.WithContext(ctx))
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return data, fmt.Errorf("wecom: HTTP %d: %s", resp.StatusCode, truncStr(data, 200))
	}
	return data, nil
}

func truncStr(b []byte, n int) string {
	if len(b) <= n {
		return string(b)
	}
	return string(b[:n]) + "..."
}

// Send 发送已构建的 payload。业务错误返回 *WeComError 且不重试。
func (c *Client) Send(ctx context.Context, payload map[string]any) (*Response, error) {
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("wecom: 序列化 payload: %w", err)
	}
	var lastErr error
	for attempt := 0; attempt <= c.retries; attempt++ {
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.webhookURL, bytes.NewReader(body))
		if err != nil {
			return nil, err
		}
		q := req.URL.Query()
		q.Set("key", c.Key)
		req.URL.RawQuery = q.Encode()
		req.Header.Set("Content-Type", "application/json")

		data, err := c.do(ctx, req)
		if err == nil {
			var r Response
			if jerr := json.Unmarshal(data, &r); jerr != nil {
				return nil, fmt.Errorf("wecom: 解析响应: %w", jerr)
			}
			if r.ErrCode != 0 {
				// 业务错误(key 无效/频率超限/消息非法)不重试, 直接返回
				return &r, &WeComError{ErrCode: r.ErrCode, ErrMsg: r.ErrMsg}
			}
			return &r, nil
		}
		lastErr = err
		if attempt < c.retries {
			wait := c.backoff * time.Duration(int64(1)<<attempt)
			select {
			case <-time.After(wait):
			case <-ctx.Done():
				return nil, ctx.Err()
			}
		}
	}
	return nil, lastErr
}

// uploadResponse upload_media 接口响应。
type uploadResponse struct {
	ErrCode   int    `json:"errcode"`
	ErrMsg    string `json:"errmsg"`
	MediaID   string `json:"media_id"`
	CreatedAt string `json:"created_at"`
	Type      string `json:"type"`
}

// UploadMedia 上传临时素材, 返回 media_id(3 天有效)。mediaType: file/image/voice。
func (c *Client) UploadMedia(ctx context.Context, path, mediaType string) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	fw, err := w.CreateFormFile("media", filepath.Base(path))
	if err != nil {
		return "", err
	}
	if _, err := fw.Write(data); err != nil {
		return "", err
	}
	if err := w.Close(); err != nil {
		return "", err
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, UploadURL, &buf)
	if err != nil {
		return "", err
	}
	q := req.URL.Query()
	q.Set("key", c.Key)
	q.Set("type", mediaType)
	req.URL.RawQuery = q.Encode()
	req.Header.Set("Content-Type", w.FormDataContentType())

	respData, err := c.do(ctx, req)
	if err != nil {
		return "", err
	}
	var ur uploadResponse
	if err := json.Unmarshal(respData, &ur); err != nil {
		return "", fmt.Errorf("wecom: 解析响应: %w", err)
	}
	if ur.ErrCode != 0 {
		return "", &WeComError{ErrCode: ur.ErrCode, ErrMsg: ur.ErrMsg}
	}
	return ur.MediaID, nil
}

// ---- 各类型便捷方法 ----

func (c *Client) SendText(ctx context.Context, content string, mentionedList, mentionedMobileList []string, mentionAll bool) (*Response, error) {
	p, err := BuildText(content, mentionedList, mentionedMobileList, mentionAll)
	if err != nil {
		return nil, err
	}
	return c.Send(ctx, p)
}

func (c *Client) SendMarkdown(ctx context.Context, content string) (*Response, error) {
	p, err := BuildMarkdown(content)
	if err != nil {
		return nil, err
	}
	return c.Send(ctx, p)
}

func (c *Client) SendImageBytes(ctx context.Context, data []byte) (*Response, error) {
	p, err := BuildImageFromBytes(data)
	if err != nil {
		return nil, err
	}
	return c.Send(ctx, p)
}

func (c *Client) SendImageFile(ctx context.Context, path string) (*Response, error) {
	p, err := BuildImageFromFile(path)
	if err != nil {
		return nil, err
	}
	return c.Send(ctx, p)
}

func (c *Client) SendNews(ctx context.Context, articles []NewsArticle) (*Response, error) {
	p, err := BuildNews(articles)
	if err != nil {
		return nil, err
	}
	return c.Send(ctx, p)
}

func (c *Client) SendFile(ctx context.Context, mediaID string) (*Response, error) {
	p, err := BuildFile(mediaID)
	if err != nil {
		return nil, err
	}
	return c.Send(ctx, p)
}

func (c *Client) SendTemplateCard(ctx context.Context, card map[string]any) (*Response, error) {
	p, err := BuildTemplateCard(card)
	if err != nil {
		return nil, err
	}
	return c.Send(ctx, p)
}
