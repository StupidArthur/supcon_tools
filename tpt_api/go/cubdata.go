package tptapi

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// cubapi/cub-data 接口（SupCon Cup 中控杯数据接口）。
//
// 端点（GET/POST 混合，统一 base URL /cubapi）：
//
//  1. datahub 读写位号接口 (Tag Value Controller)
//     - GET  /cub-data/tag/readHisData        批量读位号历史值
//     - GET  /cub-data/tag/readValues          读位号实时值
//     - POST /cub-data/tag/writeValue          写入位号实时值
//
//  2. 评分中心 (Score Center Controller)
//     - GET  /cub-data/score/getHistoryRecord  查询当前用户成绩记录
//     - POST /cub-data/score/runAlgorithm      运行算法评估（已废弃，用 V2）
//     - POST /cub-data/score/runAlgorithmV2    运行算法评估 v2
//     - POST /cub-data/score/clearMyRecords    清空当前用户成绩
//
//  3. 软测量评分 (File Controller)
//     - GET  /cub-data/file/score              查询当前用户软测量评分（最新一条）
//     - POST /cub-data/file/softSensorScore    软测量评分
//     - GET  /cub-data/file/template           下载模板文件
//     - POST /cub-data/file/upload             上传软测量预测数据文件
//
//  4. 成绩排行榜 (Ranking Controller)
//     - GET  /cub-data/ranking/all             查询所有租户成绩排名
//
//  5. 评估配置 (Eval Config Controller)
//     - GET  /cub-data/eval-config             查询评估配置
//     - POST /cub-data/eval-config             更新评估配置
//
//  6. 鉴权调试 (Auth Controller)
//     - GET  /cub-data/auth/info               解析 token 返回用户信息
//
//  7. 开发维护 (Dev Controller)
//     - GET    /cub-data/dev/tenant-detail     查询指定租户得分详情
//     - DELETE /cub-data/dev/cleanup-tenant    清空指定租户评分数据
//
//  8. 用户同步 (Auth User Sync Controller)
//     - POST /cub-data/auth-user-sync/sync     手动触发同步 TPT 系统用户
//
// 鉴权与 tpt-admin / alg-manager / ibd-data-hub 共用同一套 Bearer token + tenant cookie，
// 登录后 Client 实例可直接调用本文件函数。
//
// 响应格式：统一响应体 {code: int, message: str, data: ...}，code=200 表示成功。
// 鉴于 cub-data 的响应结构与父级（{code:"00000", msg, content}）不同，本文件方法直接返回
// 整个响应 dict（由 doRequest 在 HTTPS 模式下跳过 code 检查），由调用方从 .data 取数。

const (
	// 1. 位号读写
	CubDataReadHisDataPath      = "/cubapi/cub-data/tag/readHisData"
	CubDataReadValuesPath       = "/cubapi/cub-data/tag/readValues"
	CubDataWriteValuePath       = "/cubapi/cub-data/tag/writeValue"

	// 2. 评分中心
	CubDataScoreHistoryPath     = "/cubapi/cub-data/score/getHistoryRecord"
	CubDataScoreRunAlgoPath     = "/cubapi/cub-data/score/runAlgorithm"
	CubDataScoreRunAlgoV2Path   = "/cubapi/cub-data/score/runAlgorithmV2"
	CubDataScoreClearPath       = "/cubapi/cub-data/score/clearMyRecords"

	// 3. 软测量评分
	CubDataFileScorePath            = "/cubapi/cub-data/file/score"
	CubDataFileSoftSensorScorePath = "/cubapi/cub-data/file/softSensorScore"
	CubDataFileTemplatePath         = "/cubapi/cub-data/file/template"
	CubDataFileUploadPath           = "/cubapi/cub-data/file/upload"

	// 4. 成绩排行榜
	CubDataRankingAllPath = "/cubapi/cub-data/ranking/all"

	// 5. 评估配置
	CubDataEvalConfigPath = "/cubapi/cub-data/eval-config"

	// 6. 鉴权调试
	CubDataAuthInfoPath = "/cubapi/cub-data/auth/info"

	// 7. 开发维护
	CubDataDevTenantDetailPath  = "/cubapi/cub-data/dev/tenant-detail"
	CubDataDevCleanupTenantPath = "/cubapi/cub-data/dev/cleanup-tenant"

	// 8. 用户同步
	CubDataAuthUserSyncPath = "/cubapi/cub-data/auth-user-sync/sync"
)

// cubDataQuery 与父级 doRequest 不同：cub-data 响应无 content 字段，
// 直接返回整个 dict，调用方通过 result["data"] 取数。
//
// 行为对齐 Python _request：HTTPS 模式下 _request 跳过 code=="00000" 检查（cub-data 返回
// code=200 整数），HTTP 模式下会抛 ErrAPI。这里我们让 cub-data 方法把整响应塞进
// result["data"]，调用方需要从 result 取 data/code/message 自行判断。
//
// 为避免与父级 code==00000 校验冲突，对 cub-data 方法绕开 doRequest 统一走专用路径：
// 直接 HTTP 请求，提取整个 JSON 响应作为返回。
func (c *Client) cubDataRequest(ctx context.Context, method, path string, body any, params url.Values) (map[string]any, error) {
	u := c.baseURL + "/" + strings.TrimLeft(path, "/")
	if len(params) > 0 {
		u += "?" + params.Encode()
	}

	var bodyReader io.Reader
	if body != nil {
		jsonBody, err := json.Marshal(body)
		if err != nil {
			return nil, fmt.Errorf("marshal body: %w", err)
		}
		bodyReader = bytes.NewReader(jsonBody)
	}

	req, err := http.NewRequestWithContext(ctx, method, u, bodyReader)
	if err != nil {
		return nil, fmt.Errorf("new request: %w", err)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Accept-Language", "zh-CN")

	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	if c.tenantID != "" && c.IsHTTPS() {
		req.Header.Set("Cookie", fmt.Sprintf("TptSaasUserTenantryId=%s; tenant-id=%s", c.tenantID, c.tenantID))
	}

	resp, err := c.hc.Do(req)
	if err != nil {
		return nil, fmt.Errorf("http do: %w", err)
	}
	defer resp.Body.Close()
	rawBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read body: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, &ErrHTTP{StatusCode: resp.StatusCode, Body: string(rawBody)}
	}
	var result map[string]any
	if err := json.Unmarshal(rawBody, &result); err != nil {
		return nil, fmt.Errorf("decode response: %w (raw: %s)", err, truncate(string(rawBody), 200))
	}
	return result, nil
}

// === 1. 位号读写 (Tag Value Controller) ===

// ReadHistoryData 批量读位号历史值（GET /cub-data/tag/readHisData）。
//
// 一次查多个位号在指定时间范围内的历史值，5s 采集间隔，无分页。
//
//   - tagNames:  位号名列表；传空列表时服务端使用默认位号列表
//   - startTime: 起始时间 yyyy-MM-dd HH:mm:ss
//   - endTime:   结束时间 yyyy-MM-dd HH:mm:ss
//
// 返回: 统一响应体 dict，data 为 TagValueRow 列表，每项含 name/count/values[]。
// values 每条含 value/timeStamp/quality/alarm。
func (c *Client) ReadHistoryData(ctx context.Context, tagNames []string, startTime, endTime string) (map[string]any, error) {
	params := url.Values{}
	params.Set("startTime", startTime)
	params.Set("endTime", endTime)
	params.Set("tagNames", strings.Join(tagNames, ","))
	return c.cubDataRequest(ctx, http.MethodGet, CubDataReadHisDataPath, nil, params)
}

// ReadRealtimeValues 读位号实时值（GET /cub-data/tag/readValues）。
//
// 根据租户 ID（从 token 解析）和位号名列表读取实时值。
//
// 返回: 统一响应体 dict，data 为位号实时值列表，每项含
// name/value/quality/timeStamp/alarm。
func (c *Client) ReadRealtimeValues(ctx context.Context, tagNames []string) (map[string]any, error) {
	params := url.Values{}
	params.Set("tagNames", strings.Join(tagNames, ","))
	return c.cubDataRequest(ctx, http.MethodGet, CubDataReadValuesPath, nil, params)
}

// WriteTagValue 写入位号实时值（POST /cub-data/tag/writeValue）。
//
//   - value: 位号值，会转为字符串传输
//
// 返回: 统一响应体 dict，data 为 true 表示写入成功。
func (c *Client) WriteTagValue(ctx context.Context, tagName string, value any) (map[string]any, error) {
	params := url.Values{}
	params.Set("tagName", tagName)
	params.Set("value", fmt.Sprintf("%v", value))
	return c.cubDataRequest(ctx, http.MethodPost, CubDataWriteValuePath, nil, params)
}

// === 2. 评分中心 (Score Center Controller) ===

// GetScoreHistory 查询当前登录用户的成绩记录（GET /cub-data/score/getHistoryRecord）。
//
// 用户 ID 由服务端从 JWT 令牌解析，无需传参。
//
// 返回: 统一响应体 dict，data 为用户成绩记录列表，每项含
// id/userId/score/sci/se/ssafe/ssmi/status/algorithmType/
// startWorktime/endWorktime/algorithmStartTime/algorithmEndTime/
// isBest/retryCount/addTime/updateTime/tenantId/count。
// status: 1=评估中, 2=评估完成, 3=评估失败。
func (c *Client) GetScoreHistory(ctx context.Context) (map[string]any, error) {
	return c.cubDataRequest(ctx, http.MethodGet, CubDataScoreHistoryPath, nil, nil)
}

// RunAlgorithm 运行算法评估（POST /cub-data/score/runAlgorithm）。
//
// 已废弃，请改用 RunAlgorithmV2。
// 用户 ID 由服务端从 JWT 解析，时间范围不能超过 2 小时。
//
// 返回: 统一响应体 dict，data 为算法运行结果，含
// code(0=成功,-1=失败)/message/score/remainingTimes。
func (c *Client) RunAlgorithm(ctx context.Context, startTime, endTime string) (map[string]any, error) {
	body := map[string]any{
		"startTime": startTime,
		"endTime":   endTime,
	}
	return c.cubDataRequest(ctx, http.MethodPost, CubDataScoreRunAlgoPath, body, nil)
}

// RunAlgorithmV2 运行算法评估 v2（POST /cub-data/score/runAlgorithmV2）。
//
// 加载工况，2 小时后定时任务调用算法计算结果。
// 用户 ID 由服务端从 JWT 解析，无需传参。
//
// 返回: 统一响应体 dict，data 为用户成绩记录（status=1 评估中）。
func (c *Client) RunAlgorithmV2(ctx context.Context) (map[string]any, error) {
	return c.cubDataRequest(ctx, http.MethodPost, CubDataScoreRunAlgoV2Path, nil, nil)
}

// ClearMyRecords 清空当前登录用户的成绩（POST /cub-data/score/clearMyRecords）。
//
// 删除当前登录用户在 user_score_record、user_file 表的所有数据，
// 并清理已上传的磁盘文件。
//
// 返回: 统一响应体 dict，data 为 true 表示清空成功。
func (c *Client) ClearMyRecords(ctx context.Context) (map[string]any, error) {
	return c.cubDataRequest(ctx, http.MethodPost, CubDataScoreClearPath, nil, nil)
}

// === 3. 软测量评分 (File Controller) ===

// GetSoftSensorScore 查询当前登录用户软测量评分（GET /cub-data/file/score）。
//
// 返回最新一条上传文件记录及其评分。
//
// 返回: 统一响应体 dict，data 为用户上传文件对象，含
// id/userId/fileName/filePath/uploadTime/score/tenantId。
// score: 0-10 保留两位小数，未评分时为 null。
func (c *Client) GetSoftSensorScore(ctx context.Context) (map[string]any, error) {
	return c.cubDataRequest(ctx, http.MethodGet, CubDataFileScorePath, nil, nil)
}

// RunSoftSensorScore 软测量评分（POST /cub-data/file/softSensorScore）。
//
// 读取当前登录用户最新上传文件的 Excel B 列数据（从第 3 行开始）作为 REFERENCE.PV，
// 从考核对比的产品浓度标准文件.csv 读取 T602D_C4.PV 数据，
// 调用 concentration_fit_py 算法计算评分并更新到 user_file 记录。
//
// 返回: 统一响应体 dict，data 为算法运行结果，含
// code(0=成功,-1=失败)/message/score/remainingTimes。
func (c *Client) RunSoftSensorScore(ctx context.Context) (map[string]any, error) {
	return c.cubDataRequest(ctx, http.MethodPost, CubDataFileSoftSensorScorePath, nil, nil)
}

// DownloadTemplate 下载模板文件（GET /cub-data/file/template）。
//
//   - savePath: 保存路径，空串 = 不存文件只返回 bytes
//
// 返回: 模板文件 raw bytes。
func (c *Client) DownloadTemplate(ctx context.Context, savePath string) ([]byte, error) {
	u := c.baseURL + "/" + strings.TrimLeft(CubDataFileTemplatePath, "/")

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Accept", "application/json, text/plain, */*")
	req.Header.Set("Accept-Language", "zh-CN")
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	if c.tenantID != "" && c.IsHTTPS() {
		req.Header.Set("Cookie", fmt.Sprintf("TptSaasUserTenantryId=%s; tenant-id=%s", c.tenantID, c.tenantID))
	}

	resp, err := c.hc.Do(req)
	if err != nil {
		return nil, fmt.Errorf("http do: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(resp.Body)
		return nil, &ErrHTTP{StatusCode: resp.StatusCode, Body: string(body)}
	}

	contentType := resp.Header.Get("Content-Type")
	if strings.Contains(contentType, "json") {
		// 服务端返回了 JSON 错误而非文件
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("template download returned JSON: %s", string(body))
	}

	content, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read body: %w", err)
	}
	if savePath != "" {
		if err := os.WriteFile(savePath, content, 0644); err != nil {
			return nil, fmt.Errorf("save file: %w", err)
		}
	}
	return content, nil
}

// UploadScoreFile 上传软测量预测数据文件（POST /cub-data/file/upload）。
//
// 上传 Excel 文件，B 列从第 3 行开始为预测数据（REFERENCE.PV）。
//
// 返回: 统一响应体 dict，data 为用户上传文件对象，含
// id/userId/fileName/filePath/uploadTime/score(null)/tenantId。
func (c *Client) UploadScoreFile(ctx context.Context, filePath string) (map[string]any, error) {
	u := c.baseURL + "/" + strings.TrimLeft(CubDataFileUploadPath, "/")

	f, err := os.Open(filePath)
	if err != nil {
		return nil, fmt.Errorf("open file: %w", err)
	}
	defer f.Close()

	var buf bytes.Buffer
	writer := multipart.NewWriter(&buf)
	part, err := writer.CreateFormFile("file", filepath.Base(filePath))
	if err != nil {
		return nil, fmt.Errorf("create form file: %w", err)
	}
	if _, err := io.Copy(part, f); err != nil {
		return nil, fmt.Errorf("copy file: %w", err)
	}
	if err := writer.Close(); err != nil {
		return nil, fmt.Errorf("close multipart: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, u, &buf)
	if err != nil {
		return nil, fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("Accept", "application/json")
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	if c.tenantID != "" && c.IsHTTPS() {
		req.Header.Set("Cookie", fmt.Sprintf("TptSaasUserTenantryId=%s; tenant-id=%s", c.tenantID, c.tenantID))
	}

	resp, err := c.hc.Do(req)
	if err != nil {
		return nil, fmt.Errorf("http do: %w", err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read body: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, &ErrHTTP{StatusCode: resp.StatusCode, Body: string(raw)}
	}
	var result map[string]any
	if err := json.Unmarshal(raw, &result); err != nil {
		return nil, fmt.Errorf("decode response: %w (raw: %s)", err, truncate(string(raw), 200))
	}
	return result, nil
}

// === 4. 成绩排行榜 (Ranking Controller) ===

// GetRankingAll 查询所有租户成绩排名（GET /cub-data/ranking/all）。
//
// 返回: 统一响应体 dict，data 为租户成绩排名列表，每项含：
// tenantId / controlScore / softSensorScore / totalScore / rank。
//   - controlScore:   控制最优成绩（is_best=true 的最高分），无成绩时 null
//   - softSensorScore: 软测量成绩（user_file 最高分），无成绩时 null
//   - totalScore:      总分 = 控制最优×0.8 + 软测量×0.2，缺失项按 0，保留 5 位小数
//   - rank:            排名（按总分降序，同分同排名）
func (c *Client) GetRankingAll(ctx context.Context) (map[string]any, error) {
	return c.cubDataRequest(ctx, http.MethodGet, CubDataRankingAllPath, nil, nil)
}

// === 5. 评估配置 (Eval Config Controller) ===

// GetEvalConfig 查询评估配置（GET /cub-data/eval-config）。
//
// 读取单行评估配置（id=1），不存在时自动初始化默认配置。
//
// 返回: 统一响应体 dict，data 为评估配置对象，含
// id/pracLoadEnabled/examLoadEnabled/evalDurationMinutes/addTime/updateTime。
// pracLoadEnabled: 1=开启练习工况, 0=关闭。
// examLoadEnabled: 1=开启考试工况, 0=关闭。
// evalDurationMinutes: 评估时间段（分钟）。
func (c *Client) GetEvalConfig(ctx context.Context) (map[string]any, error) {
	return c.cubDataRequest(ctx, http.MethodGet, CubDataEvalConfigPath, nil, nil)
}

// UpdateEvalConfig 更新评估配置（POST /cub-data/eval-config）。
//
// 可修改 pracLoadEnabled / examLoadEnabled / evalDurationMinutes /
// startWorktimeDelayMinutes 四个字段，id 由服务端强制为 1（单行配置表约束）。
//
// 参数任意一个传 nil 表示不修改该字段。
func (c *Client) UpdateEvalConfig(ctx context.Context, pracLoadEnabled, examLoadEnabled, evalDurationMinutes, startWorktimeDelayMinutes *int) (map[string]any, error) {
	body := map[string]any{}
	if pracLoadEnabled != nil {
		body["pracLoadEnabled"] = *pracLoadEnabled
	}
	if examLoadEnabled != nil {
		body["examLoadEnabled"] = *examLoadEnabled
	}
	if evalDurationMinutes != nil {
		body["evalDurationMinutes"] = *evalDurationMinutes
	}
	if startWorktimeDelayMinutes != nil {
		body["startWorktimeDelayMinutes"] = *startWorktimeDelayMinutes
	}
	return c.cubDataRequest(ctx, http.MethodPost, CubDataEvalConfigPath, body, nil)
}

// === 6. 鉴权调试 (Auth Controller) ===

// GetAuthInfo 解析 Authorization 头中的 token（GET /cub-data/auth/info）。
//
// 解析 JWT 令牌并返回其中的用户信息。
//
// 返回: 统一响应体 dict，data 为鉴权信息对象，含
// userId/username/nickName/type/exp/expired/valid/message。
func (c *Client) GetAuthInfo(ctx context.Context) (map[string]any, error) {
	return c.cubDataRequest(ctx, http.MethodGet, CubDataAuthInfoPath, nil, nil)
}

// === 7. 开发维护 (Dev Controller) ===

// GetTenantDetail 查询指定租户的得分详情（GET /cub-data/dev/tenant-detail）。
//
// 需要管理员权限。返回指定租户的控制成绩记录和软测量评分记录。
//
// 返回: 统一响应体 dict，data 为 Map，包含控制成绩记录和软测量评分记录。
func (c *Client) GetTenantDetail(ctx context.Context, tenantID string) (map[string]any, error) {
	params := url.Values{}
	params.Set("tenantId", tenantID)
	return c.cubDataRequest(ctx, http.MethodGet, CubDataDevTenantDetailPath, nil, params)
}

// CleanupTenant 清空指定租户的评分相关数据（DELETE /cub-data/dev/cleanup-tenant）。
//
// 需要管理员权限。删除指定租户的成绩记录、上传文件记录及磁盘文件。
//
// 返回: 统一响应体 dict，data 为清理数量统计（Map<string,int>）。
func (c *Client) CleanupTenant(ctx context.Context, tenantID string) (map[string]any, error) {
	params := url.Values{}
	params.Set("tenantId", tenantID)
	return c.cubDataRequest(ctx, http.MethodDelete, CubDataDevCleanupTenantPath, nil, params)
}

// === 8. 用户同步 (Auth User Sync Controller) ===

// SyncAuthUsers 手动触发同步 TPT 系统用户（POST /cub-data/auth-user-sync/sync）。
//
// 立即从 TPT 系统拉取用户列表并同步到本服务 auth_user 表，
// 返回同步成功的用户数量；失败返回 -1。
//
//   - updateTimeBegin: 查询起始时间 yyyy-MM-dd HH:mm:ss，不传则取当前时间。
//     调试建议传较早时间以拉全量，如 "2020-01-01 00:00:00"
//
// 返回: 统一响应体 dict，data 为同步成功的用户数量（int）。
func (c *Client) SyncAuthUsers(ctx context.Context, updateTimeBegin string) (map[string]any, error) {
	var params url.Values
	if updateTimeBegin != "" {
		params = url.Values{}
		params.Set("updateTimeBegin", updateTimeBegin)
	}
	return c.cubDataRequest(ctx, http.MethodPost, CubDataAuthUserSyncPath, nil, params)
}

// Suppress unused import "strconv" if not needed elsewhere; kept for symmetry with Python int().
var _ = strconv.Itoa
