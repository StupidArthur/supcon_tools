package collector

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/url"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"

	"raymonitor/logx"
)

func (c *Client) logRequest(path string, status int, started time.Time, header http.Header, decodedBytes int, err error) {
	endpoint := observationEndpoint(path)
	attrs := []any{
		"cluster", c.clusterID,
		"base_url", safeBaseURL(c.baseURL),
		"endpoint", endpoint,
		"status", status,
		"duration_ms", time.Since(started).Milliseconds(),
		"decoded_bytes", decodedBytes,
	}
	if header != nil {
		attrs = append(attrs,
			"content_type", header.Get("Content-Type"),
			"content_encoding", header.Get("Content-Encoding"),
			"content_length", header.Get("Content-Length"),
			"server", header.Get("Server"),
			"ray_version", firstHeader(header, "X-Ray-Version", "Ray-Version"),
		)
	}
	if err != nil {
		attrs = append(attrs, "ok", false, "error", err.Error())
		logx.Event("error", "ray_http_request_failed", attrs...)
	} else {
		attrs = append(attrs, "ok", true)
	}
	logx.Event("api", "ray_http_request", attrs...)
}

func (c *Client) observeSchema(path string, data []byte, header http.Header) {
	// Schema 观测日志默认关闭：不同节点 Actor 字段组合差异导致指纹频繁变化，
	// 生产一日可产生 20MB+ 日志（environment_*.jsonl），价值低。
	// 需调试 Ray 接口形状时设置环境变量 RAY_MONITOR_OBSERVE_SCHEMA=1 重新开启。
	if os.Getenv("RAY_MONITOR_OBSERVE_SCHEMA") == "" {
		return
	}
	var value any
	if err := json.Unmarshal(data, &value); err != nil {
		logx.Event("error", "ray_json_shape_failed",
			"cluster", c.clusterID, "endpoint", observationEndpoint(path),
			"decoded_bytes", len(data), "error", err.Error())
		return
	}
	shape := make(map[string]bool)
	collectJSONShape("$", value, 0, shape)
	paths := make([]string, 0, len(shape))
	for item := range shape {
		paths = append(paths, item)
	}
	sort.Strings(paths)
	if len(paths) > 300 {
		paths = paths[:300]
	}
	sum := sha256.Sum256([]byte(strings.Join(paths, "\n")))
	fingerprint := hex.EncodeToString(sum[:8])
	endpoint := observationEndpoint(path)

	c.mu.Lock()
	previous := c.schemaByAPI[endpoint]
	if previous != fingerprint {
		c.schemaByAPI[endpoint] = fingerprint
	}
	c.mu.Unlock()
	if previous == fingerprint {
		return
	}

	logx.Event("environment", "ray_response_schema",
		"cluster", c.clusterID,
		"base_url", safeBaseURL(c.baseURL),
		"endpoint", endpoint,
		"schema_fingerprint", fingerprint,
		"schema_changed", previous != "",
		"previous_fingerprint", previous,
		"decoded_bytes", len(data),
		"content_type", header.Get("Content-Type"),
		"content_encoding", header.Get("Content-Encoding"),
		"server", header.Get("Server"),
		"ray_version", firstHeader(header, "X-Ray-Version", "Ray-Version"),
		"json_shape", paths,
	)
}

func collectJSONShape(path string, value any, depth int, out map[string]bool) {
	if depth > 8 || len(out) >= 400 {
		return
	}
	switch typed := value.(type) {
	case map[string]any:
		out[path+":object"] = true
		keys := make([]string, 0, len(typed))
		for key := range typed {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		for _, key := range keys {
			nextKey := key
			if strings.HasSuffix(path, ".actors") {
				nextKey = "*"
			}
			collectJSONShape(path+"."+nextKey, typed[key], depth+1, out)
			if nextKey == "*" {
				break
			}
		}
	case []any:
		out[path+":array"] = true
		for i := 0; i < len(typed) && i < 3; i++ {
			collectJSONShape(path+"[]", typed[i], depth+1, out)
		}
	case string:
		out[path+":string"] = true
	case float64:
		out[path+":number"] = true
	case bool:
		out[path+":boolean"] = true
	case nil:
		out[path+":null"] = true
	default:
		out[path+":"+strconv.Itoa(depth)] = true
	}
}

func observationEndpoint(path string) string {
	if strings.HasPrefix(path, "/nodes/") {
		return "/nodes/{nodeId}"
	}
	return path
}

func safeBaseURL(raw string) string {
	parsed, err := url.Parse(raw)
	if err != nil {
		return raw
	}
	return parsed.Scheme + "://" + parsed.Host
}

func firstHeader(header http.Header, names ...string) string {
	for _, name := range names {
		if value := header.Get(name); value != "" {
			return value
		}
	}
	return ""
}
