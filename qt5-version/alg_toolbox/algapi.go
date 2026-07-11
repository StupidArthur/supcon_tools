package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// AlgAPI 封装算法平台的全部 API 调用。
// 对应 Python 版 common/api.py 的 AlgAPI 类，支持 HTTP 和 HTTPS（多租户）两种模式。
type AlgAPI struct {
	baseURL    string
	token      string
	httpsMode  bool
	client     *http.Client
	algorithms []map[string]any // 缓存 get_all_algorithms 的结果
	sourceMap  map[string]map[string]any // sourcePath -> 算法完整信息
}

// APIError 携带鉴权错误标记，前端据此提示"可能是登录已过期"。
type APIError struct {
	Code        string
	Msg         string
	IsAuthError bool
}

func (e *APIError) Error() string {
	return fmt.Sprintf("[%s] %s", e.Code, e.Msg)
}

// NewAlgAPI 创建平台 API 客户端。
func NewAlgAPI(baseURL string) *AlgAPI {
	baseURL = strings.TrimRight(baseURL, "/")
	return &AlgAPI{
		baseURL:   baseURL,
		httpsMode: strings.HasPrefix(baseURL, "https://"),
		client:    &http.Client{Timeout: 30 * time.Second},
		sourceMap: make(map[string]map[string]any),
	}
}

// request 是通用请求方法，对应 Python _request。
// wrap=true 时将 body 包裹在 {"data": body} 中；wrap=false 时 body 直接作为 JSON body。
func (a *AlgAPI) request(method, path string, body any, params url.Values, wrap bool) (any, error) {
	u := a.baseURL + "/" + strings.TrimLeft(path, "/")
	if params != nil {
		u += "?" + params.Encode()
	}

	var bodyReader io.Reader
	if body != nil {
		var jsonBody []byte
		var err error
		if wrap {
			jsonBody, err = json.Marshal(map[string]any{"data": body})
		} else {
			jsonBody, err = json.Marshal(body)
		}
		if err != nil {
			return nil, fmt.Errorf("JSON 编码失败: %w", err)
		}
		bodyReader = bytes.NewReader(jsonBody)
	}

	req, err := http.NewRequest(method, u, bodyReader)
	if err != nil {
		return nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}

	resp, err := a.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var data map[string]any
	if err := json.Unmarshal(raw, &data); err != nil {
		return nil, fmt.Errorf("响应解析失败: %s", string(raw))
	}

	code, _ := data["code"].(string)
	isSuccess, _ := data["isSuccess"].(bool)

	// 成功判断：code=="00000"，或 HTTPS 模式下 isSuccess 为 false（兼容 HTTPS 返回格式）
	if code != "00000" && !(a.httpsMode && !isSuccess) {
		msg, _ := data["msg"].(string)
		return nil, &APIError{
			Code:        code,
			Msg:         msg,
			IsAuthError: a.isAuthError(data),
		}
	}

	if content, ok := data["content"]; ok {
		return content, nil
	}
	return data, nil
}

// isAuthError 判断是否为鉴权错误，对应 Python _is_auth_error。
func (a *AlgAPI) isAuthError(data map[string]any) bool {
	code := fmt.Sprintf("%v", data["code"])
	authCodes := map[string]bool{"A0230": true, "A0201": true, "A0202": true, "A0203": true}
	if authCodes[code] {
		return true
	}
	msg, _ := data["msg"].(string)
	keywords := []string{"未登录", "登录已超时", "登录过期", "token过期", "无访问权限", "Unauthorized"}
	for _, k := range keywords {
		if strings.Contains(msg, k) {
			return true
		}
	}
	return false
}

// Login 登录平台获取 Bearer Token。
func (a *AlgAPI) Login(username, password, tenantID string) error {
	body := map[string]any{
		"username":     username,
		"password":     password,
		"remember":     false,
		"accountType":  "0",
		"generateCode": false,
	}

	if a.httpsMode && tenantID != "" {
		body["tenantId"] = tenantID
	}

	// HTTPS 模式：登录请求本身也要带 tenantId cookie（与 Python common/api.py 行为一致）。
	// 先用一个临时 transport 让登录 POST 携带 cookie，登录完成后再用真实 token 替换。
	if a.httpsMode && tenantID != "" {
		a.client.Transport = &authTransport{
			base:      http.DefaultTransport,
			httpsMode: true,
			tenantID:  tenantID,
		}
	}

	result, err := a.request("POST", "/tpt-admin/system-manager/umsAdmin/login", body, nil, true)
	if err != nil {
		return err
	}

	resultMap, ok := result.(map[string]any)
	if !ok {
		return fmt.Errorf("登录响应格式异常")
	}

	token, _ := resultMap["token"].(string)
	if token == "" {
		return fmt.Errorf("登录响应中未找到 token")
	}

	a.token = token
	// 后续请求自动携带 Bearer Token
	a.client.Transport = &authTransport{
		base:      http.DefaultTransport,
		token:     token,
		httpsMode: a.httpsMode,
		tenantID:  tenantID,
	}
	return nil
}

// authTransport 在每个请求中注入认证信息（Bearer Token + HTTPS 模式的 Cookie）。
type authTransport struct {
	base      http.RoundTripper
	token     string
	httpsMode bool
	tenantID  string
}

func (t *authTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	if t.token != "" {
		req.Header.Set("Authorization", "Bearer "+t.token)
	}
	if t.httpsMode && t.tenantID != "" {
		req.AddCookie(&http.Cookie{Name: "tpt-token", Value: t.token})
		// 注意：cookie 名 "TenanTryId" 是平台侧的实际拼写（多一个 r），与 Python 端保持一致
		req.AddCookie(&http.Cookie{Name: "TptSaasUserTenantryId", Value: t.tenantID})
		req.AddCookie(&http.Cookie{Name: "tenant-id", Value: t.tenantID})
	}
	base := t.base
	if base == nil {
		base = http.DefaultTransport
	}
	return base.RoundTrip(req)
}

// ListAlgorithms 获取算法列表（单页），对应 Python list_algorithms。
func (a *AlgAPI) ListAlgorithms(page, pageSize int) (map[string]any, error) {
	body := map[string]any{
		"data": map[string]any{
			"createTime_begin": "",
			"createTime_end":   "",
		},
		"requestBase": map[string]any{
			"page": fmt.Sprintf("%d-%d", page, pageSize),
			"sort": "-createTime",
		},
	}
	params := url.Values{"extend": {"0"}}

	result, err := a.request("POST", "/alg-manager-web-v2.2-tpt/api/algorithm/page/1", body, params, false)
	if err != nil {
		return nil, err
	}
	resultMap, ok := result.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("算法列表响应格式异常")
	}
	return resultMap, nil
}

// GetAllAlgorithms 自动翻页获取所有算法并缓存，对应 Python get_all_algorithms。
func (a *AlgAPI) GetAllAlgorithms() ([]map[string]any, error) {
	pageSize := 100
	page := 1
	var allRecords []map[string]any

	for {
		result, err := a.ListAlgorithms(page, pageSize)
		if err != nil {
			return nil, err
		}

		recordsRaw, _ := result["records"].([]any)
		if len(recordsRaw) == 0 {
			break
		}

		for _, r := range recordsRaw {
			if record, ok := r.(map[string]any); ok {
				allRecords = append(allRecords, record)
			}
		}

		if len(recordsRaw) < pageSize {
			break
		}
		page++
	}

	a.algorithms = allRecords
	a.sourceMap = make(map[string]map[string]any)
	for _, algo := range allRecords {
		if sourcePath, _ := algo["sourcePath"].(string); sourcePath != "" {
			a.sourceMap[sourcePath] = algo
		}
	}
	return allRecords, nil
}

// GetBySourcePath 通过 sourcePath 获取缓存的算法信息。
func (a *AlgAPI) GetBySourcePath(sourcePath string) map[string]any {
	return a.sourceMap[sourcePath]
}

// GetByID 通过 id 获取缓存的算法信息。
func (a *AlgAPI) GetByID(algoID float64) map[string]any {
	for _, algo := range a.algorithms {
		if id, _ := algo["id"].(float64); id == algoID {
			return algo
		}
	}
	return nil
}

// ReleaseAlgorithm 发布或取消发布算法，对应 Python release_algorithm。
// isRelease: 0=取消发布, 1=发布; resourceType: 1=CPU, 2=GPU
func (a *AlgAPI) ReleaseAlgorithm(algoID float64, isRelease, cores, resourceType, numReplicas int) error {
	body := map[string]any{
		"id":            algoID,
		"isRelease":     isRelease,
		"cores":         cores,
		"resourceType":  resourceType,
		"numReplicas":   numReplicas,
	}
	_, err := a.request("POST", "/alg-manager-web-v2.2-tpt/api/algorithm/release", body, nil, false)
	return err
}

// UploadFile 上传 zip 文件到 MinIO，对应 Python upload_file。
func (a *AlgAPI) UploadFile(filePath string) (map[string]any, error) {
	u := a.baseURL + "/alg-manager-web-v2.2-tpt/encryption/upload_file_to_minio"

	file, err := os.Open(filePath)
	if err != nil {
		return nil, fmt.Errorf("打开文件失败: %w", err)
	}
	defer file.Close()

	var buf bytes.Buffer
	writer := multipart.NewWriter(&buf)
	part, err := writer.CreateFormFile("file", filepath.Base(filePath))
	if err != nil {
		return nil, err
	}
	if _, err := io.Copy(part, file); err != nil {
		return nil, err
	}
	writer.Close()

	req, err := http.NewRequest("POST", u+"?built_in=1", &buf)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())

	resp, err := a.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var data map[string]any
	if err := json.Unmarshal(raw, &data); err != nil {
		return nil, fmt.Errorf("上传响应解析失败: %s", string(raw))
	}
	return data, nil
}

// EditAlgorithm 提交算法信息（需先上传文件），对应 Python edit_algorithm。
// 从缓存中读取算法信息，自动拼接 type 字段，以 multipart/form-data 提交。
func (a *AlgAPI) EditAlgorithm(sourcePath string) (map[string]any, error) {
	info := a.sourceMap[sourcePath]
	if info == nil {
		return nil, fmt.Errorf("未找到算法: source_path=%s", sourcePath)
	}

	// 深拷贝算法信息，追加 type 字段
	algoInfo := make(map[string]any)
	for k, v := range info {
		algoInfo[k] = v
	}
	categoryOne, _ := algoInfo["categoryOne"].(float64)
	if categoryOne == 0 {
		categoryOne = 1
	}
	categoryTwo, _ := algoInfo["categoryTwo"].(float64)
	algoInfo["type"] = fmt.Sprintf("%v-%v", categoryOne, categoryTwo)

	algorithmJSON, err := json.Marshal(algoInfo)
	if err != nil {
		return nil, err
	}

	u := a.baseURL + "/alg-manager-web-v2.2-tpt/api/algorithm/edit/1"

	var buf bytes.Buffer
	writer := multipart.NewWriter(&buf)
	// 字段名 algorithm，值为 JSON 字符串，Content-Type 为 application/json
	h := make(map[string][]string)
	h["Content-Disposition"] = []string{fmt.Sprintf(`form-data; name="algorithm"; filename="blob"`)}
	h["Content-Type"] = []string{"application/json"}
	fieldWriter, err := writer.CreatePart(h)
	if err != nil {
		return nil, err
	}
	fieldWriter.Write(algorithmJSON)
	writer.Close()

	req, err := http.NewRequest("POST", u, &buf)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())

	resp, err := a.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var data map[string]any
	if err := json.Unmarshal(raw, &data); err != nil {
		return nil, fmt.Errorf("编辑响应解析失败: %s", string(raw))
	}

	code, _ := data["code"].(string)
	if code != "00000" {
		msg, _ := data["msg"].(string)
		return nil, &APIError{Code: code, Msg: msg, IsAuthError: a.isAuthError(data)}
	}

	if content, ok := data["content"].(map[string]any); ok {
		return content, nil
	}
	return data, nil
}

// MatchLocalFiles 用本地文件名匹配平台 sourcePath，对应 Python match_local_files。
// 匹配到的条目包含算法全部字段 + name + isExist=true；未匹配的条目只有 name + isExist=false。
func (a *AlgAPI) MatchLocalFiles(resourceDir string) ([]map[string]any, error) {
	localFiles, err := listLocalResources(resourceDir)
	if err != nil {
		return nil, err
	}

	var result []map[string]any
	for _, f := range localFiles {
		if info, ok := a.sourceMap[f]; ok {
			item := make(map[string]any)
			for k, v := range info {
				item[k] = v
			}
			item["name"] = f
			item["isExist"] = true
			// cores 转为 int（平台返回可能是 float64）
			if cores, ok := item["cores"].(float64); ok {
				item["cores"] = int(cores)
			}
			result = append(result, item)
		} else {
			result = append(result, map[string]any{
				"name":    f,
				"isExist": false,
			})
		}
	}
	return result, nil
}

// listLocalResources 读取指定目录下所有 .zip 和 .py 文件名。
func listLocalResources(dirPath string) ([]string, error) {
	entries, err := os.ReadDir(dirPath)
	if err != nil {
		return nil, err
	}
	var files []string
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		if strings.HasSuffix(name, ".zip") || strings.HasSuffix(name, ".py") {
			files = append(files, name)
		}
	}
	return files, nil
}
