package rw

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/yzc/tpt_api"
)

// Service 业务能力:登录后做 "登录态下的 TPT 值读写" 业务用例。
//
// 设计要点:
//   - 通过 ClientPort 拿到 *tptapi.TptClient(由 container 注入,内置 token 续期)。
//   - 所有调用都做绑定,遇到 *tptapi.TptAPIError / 其它错误时统一翻译成 *PublicError。
//   - 写值回读为可选 + 延时,默认 1s(平台实测 ~1s RT 反映,~4s 历史落库,见 tpt_api/README.md)。
type Service struct {
	client ClientPort
}

// NewService 创建 rw.Service。client 由 container 注入(真实 = *tptapi.TptClient)。
func NewService(client ClientPort) *Service {
	return &Service{client: client}
}

// ListDataSources 拉全部数据源。空表返回 nil,len=0。
func (s *Service) ListDataSources(ctx context.Context) ([]DataSource, error) {
	if ctx.Err() != nil {
		return nil, &PublicError{Message: "操作已取消", Kind: "input"}
	}
	srcs, err := s.client.GetAllDsInfo()
	if err != nil {
		return nil, MapError(err)
	}
	out := make([]DataSource, 0, len(srcs))
	for _, d := range srcs {
		out = append(out, DataSource{
			ID: d.ID, Name: d.DsName, URL: d.DsTarUrl,
			Type: d.DsType, SubType: d.DsSubType,
			Alive: d.Alive, DsStatus: d.DsStatus,
		})
	}
	return out, nil
}

// ListTags 经 queryWithQuality 拉位号(含实时值)。
// 当 Keyword 为空时改走 /tag-group/get(endpoint ListGroupTags),
//
//	响应结构与 queryWithQuality 不同(tagInfoList.records[]),由 parseGroupTagsResponse 单独解。
// 选这条退路是因为:实平台 queryWithQuality 在 tagName="" 路径上不返 records
// (或返 pageinfo dict),导致用户不输入任何关键字就显示 "已加载 0 条"。
//
// 空关键字路径下,/tag-group/get 端点不接受 DSID 参数,平台会返回所有数据源的位号。
// 当 q.DSID 非 nil 时,service 层在客户端按 tag.DSID == *q.DSID 过滤,避免用户选到
// 不属于当前选中数据源的位号。
//
// 注意:空关键字路径下 q.TagType=0 会被底层 tpt_api.ListGroupTags 改写为 TagTypeOnce
// (只查一次位号),与 QueryTagsWithQuality 路径的"0=不过滤"语义不同。这是共享代码层
// 行为,本任务不修。
func (s *Service) ListTags(ctx context.Context, q TagListQuery) ([]Tag, error) {
	if ctx.Err() != nil {
		return nil, &PublicError{Message: "操作已取消", Kind: "input"}
	}
	if q.GroupID == "" {
		q.GroupID = tptapi.GroupRoot
	}
	if q.Page == 0 {
		q.Page = 1
	}
	if q.PageSize == 0 {
		q.PageSize = 200
	}
	if q.Sort == "" {
		q.Sort = "-createTime"
	}
	if q.Keyword == "" {
		// 走 /tag-group/get 空关键字路径
		raw, err := s.client.ListGroupTagsRaw(q.GroupID, "", q.TagType, q.Page, q.PageSize)
		if err != nil {
			return nil, MapError(err)
		}
		tags, err := parseGroupTagsResponse(raw)
		if err != nil {
			return nil, err
		}
		if q.DSID != nil {
			filtered := make([]Tag, 0, len(tags))
			for _, t := range tags {
				if t.DSID == *q.DSID {
					filtered = append(filtered, t)
				}
			}
			tags = filtered
		}
		return tags, nil
	}
	raw, err := s.client.QueryTagsWithQuality(q.DSID, q.GroupID, q.Keyword, "",
		q.TagType, q.Page, q.PageSize, q.Sort)
	if err != nil {
		return nil, MapError(err)
	}
	return parseQueryWithQualityResponse(raw)
}

// parseGroupTagsResponse 解 /tag-group/get 的响应。
// 兼容 queryWithQuality 的所有形态 + /tag-group/get 特有的 tagInfoList.records。
// 即使 /tag-group/get 在不同平台上吐不同形态也能兜底。
func parseGroupTagsResponse(raw json.RawMessage) ([]Tag, error) {
	s := bytes.TrimSpace(raw)
	if len(s) == 0 || string(s) == "null" {
		return []Tag{}, nil
	}

	// 形态:裸数组
	if s[0] == '[' {
		var bare []Tag
		if err := json.Unmarshal(raw, &bare); err != nil {
			return nil, MapError(fmt.Errorf("groupTags 解析失败(裸数组): %w", err))
		}
		if bare == nil {
			bare = []Tag{}
		}
		return bare, nil
	}

	// 形态:dict,尝试 records/data/list/tagInfoList.records 四个键
	if s[0] == '{' {
		var wrapped struct {
			TagInfoList struct {
				Records []Tag `json:"records"`
			} `json:"tagInfoList"`
			Records []Tag `json:"records"`
			Data    []Tag `json:"data"`
			List    []Tag `json:"list"`
		}
		if err := json.Unmarshal(raw, &wrapped); err != nil {
			return nil, MapError(fmt.Errorf("groupTags 解析失败(dict): %w", err))
		}
		switch {
		case len(wrapped.TagInfoList.Records) > 0:
			return wrapped.TagInfoList.Records, nil
		case len(wrapped.Records) > 0:
			return wrapped.Records, nil
		case len(wrapped.Data) > 0:
			return wrapped.Data, nil
		case len(wrapped.List) > 0:
			return wrapped.List, nil
		}
		return []Tag{}, nil
	}

	return nil, MapError(fmt.Errorf("groupTags 响应首字符异常: %s", truncateForErr(raw, 80)))
}

// parseQueryWithQualityResponse 解 queryWithQuality 三种已知形态,失败给出可读错误。
//
// 形态 1:裸数组 [{...},{...}]                       (常见真实环境与 fixture 都可能给出)
// 形态 2:{"records":[{"...":...},{...}]}             (Python 端对齐参考: ua2_query_runtime.py:185)
// 形态 3:{"data":[{"...":...},{...}]}                (同字段别名)
//
// **重要**:**不要**先用 `Unmarshal(target=struct)` 后看 `Records != nil` 兜底 ——
//
//	未知字段被忽略、Records 留为 nil slice,看上去"成功 + 0 条"会让你误以为无数据;
//	然后回退到 `Unmarshal(target=[]Tag)` 时,object 又与目标切片不兼容,会报
//	"cannot unmarshal object into Go slice of type"。真平台响应就是这种 dict-but-no-records
//	的情况。
//
// 改为按 raw 首字符严格路由:首字符 `[` 走裸数组,首字符 `{` 走 dict(尝试 records/data/list 三个键),
//否则判空,真正失败时给出"json: invalid character ..." 而不是后来那次伪成功的覆盖。
func parseQueryWithQualityResponse(raw json.RawMessage) ([]Tag, error) {
	s := bytes.TrimSpace(raw)
	if len(s) == 0 || string(s) == "null" {
		return []Tag{}, nil
	}

	// 形态 1:裸数组
	if s[0] == '[' {
		var bare []Tag
		if err := json.Unmarshal(raw, &bare); err != nil {
			return nil, MapError(fmt.Errorf("queryWithQuality 解析失败(裸数组): %w", err))
		}
		if bare == nil {
			bare = []Tag{}
		}
		return bare, nil
	}

	// 形态 2 / 3:dict,尝试常见字段
	if s[0] == '{' {
		for _, key := range []string{"records", "data", "list"} {
			var wrapped struct {
				Records []Tag `json:"records"`
				Data    []Tag `json:"data"`
				List    []Tag `json:"list"`
			}
			if err := json.Unmarshal(raw, &wrapped); err != nil {
				return nil, MapError(fmt.Errorf("queryWithQuality 解析失败(dict): %w", err))
			}
			switch key {
			case "records":
				if wrapped.Records != nil {
					return wrapped.Records, nil
				}
			case "data":
				if wrapped.Data != nil {
					return wrapped.Data, nil
				}
			case "list":
				if wrapped.List != nil {
					return wrapped.List, nil
				}
			}
		}
		// 没有命中任一字段 → 平台确实返回了空列表(dict 但所有 keys 缺失)
		return []Tag{}, nil
	}

	return nil, MapError(fmt.Errorf("queryWithQuality 响应首字符既不是 [ 也不是 { : %s", truncateForErr(raw, 80)))
}

// ReadRealtime 按 tag 名列表读实时值。
func (s *Service) ReadRealtime(ctx context.Context, tagNames []string) ([]RTValue, error) {
	if ctx.Err() != nil {
		return nil, &PublicError{Message: "操作已取消", Kind: "input"}
	}
	if len(tagNames) == 0 {
		return []RTValue{}, nil
	}
	pts, err := s.client.GetRTValue(tagNames)
	if err != nil {
		return nil, MapError(err)
	}
	out := make([]RTValue, 0, len(pts))
	for _, p := range pts {
		out = append(out, RTValue{
			TagName: p.TagName, Value: p.TagValue,
			TagTime: p.TagTime, AppTime: p.AppTime,
			Quality: p.Quality, DataType: p.DataType, DSID: p.DsID,
			IsSuccess: p.IsSuccess, Message: p.Message,
		})
	}
	return out, nil
}

// WriteValues 写值 + 可选 ~1s 回读。
//
// Fails 来自平台响应 failMsg(写失败)和回读中 IsSuccess=false / 无数据的点。
func (s *Service) WriteValues(ctx context.Context, req WriteRequest) (*WriteResult, error) {
	if ctx.Err() != nil {
		return nil, &PublicError{Message: "操作已取消", Kind: "input"}
	}
	if len(req.Values) == 0 {
		return &WriteResult{}, MapError(fmt.Errorf("values 不能为空"))
	}
	writeRes, err := s.client.WriteTagValues(req.Values)
	if err != nil {
		return nil, MapError(err)
	}
	res := &WriteResult{
		Written: writeRes.TagNames,
	}
	if len(writeRes.FailMsg) > 0 {
		res.Fails = make(map[string]string, len(writeRes.FailMsg))
		for k, v := range writeRes.FailMsg {
			res.Fails[k] = v
		}
	}
	if req.ReadbackDelay <= 0 {
		// 无回读:若平台未报 failMsg,Written 用 Values 的 key 集(平台成功时不一定返回 tagNames)
		if len(res.Written) == 0 && len(res.Fails) == 0 {
			res.Written = make([]string, 0, len(req.Values))
			for k := range req.Values {
				res.Written = append(res.Written, k)
			}
		}
		return res, nil
	}
	// 同步等待,简单可靠。GUI 用户一次操作大概等得起 1s。
	select {
	case <-ctx.Done():
		// 取消:写入已完成,但回读被取消。返回已有结果 + readback 取消标记。
		if res.Fails == nil {
			res.Fails = make(map[string]string)
		}
		res.Fails["readback"] = "已取消: " + ctx.Err().Error()
		return res, nil
	case <-time.After(req.ReadbackDelay):
	}
	tagNames := req.ReadbackTagNames
	if len(tagNames) == 0 {
		tagNames = make([]string, 0, len(req.Values))
		for k := range req.Values {
			tagNames = append(tagNames, k)
		}
	}
	pts, err := s.client.GetRTValue(tagNames)
	if err != nil {
		if res.Fails == nil {
			res.Fails = make(map[string]string)
		}
		res.Fails["readback"] = err.Error()
		return res, nil
	}
	res.Readback = make([]RTValue, 0, len(pts))
	for _, p := range pts {
		res.Readback = append(res.Readback, RTValue{
			TagName: p.TagName, Value: p.TagValue,
			TagTime: p.TagTime, AppTime: p.AppTime,
			Quality: p.Quality, DataType: p.DataType, DSID: p.DsID,
			IsSuccess: p.IsSuccess, Message: p.Message,
		})
		if !p.IsSuccess {
			if res.Fails == nil {
				res.Fails = make(map[string]string)
			}
			res.Fails[p.TagName] = p.Message
		}
	}
	// 若平台未返回 tagNames 且无 failMsg,用 Values key 集
	if len(res.Written) == 0 && len(res.Fails) == 0 {
		res.Written = tagNames
	}
	return res, nil
}

// ReadHistory 按 q.Mode 路由到 /getHistoryValue 或 /getHistoryValueFromDB。
func (s *Service) ReadHistory(ctx context.Context, q HistoryQuery) ([]HistoryRow, error) {
	if ctx.Err() != nil {
		return nil, &PublicError{Message: "操作已取消", Kind: "input"}
	}
	if len(q.TagNames) == 0 {
		return []HistoryRow{}, nil
	}
	if q.Sort == "" {
		q.Sort = "-appTime"
	}
	if q.Page == 0 {
		q.Page = 1
	}
	if q.PageSize == 0 {
		q.PageSize = 200
	}
	var raw json.RawMessage
	var err error
	if q.Mode == ModeFromDB {
		raw, err = s.client.GetHistoryValueFromDB(q.TagNames, q.BegTime, q.EndTime,
			q.IsSource, q.NumberToString, q.Page, q.PageSize, q.Sort)
	} else {
		raw, err = s.client.GetHistoryValue(q.TagNames, q.BegTime, q.EndTime,
			q.Interval, q.IsSecond, q.IsSource, q.Offset, q.Option,
			q.Page, q.PageSize, q.Sort)
	}
	if err != nil {
		return nil, MapError(err)
	}
	// /getHistoryValue(page): IPage {"records": [...], "total": N, "current":..., "size":..., "pages":...}
	// /getHistoryValueFromDB(fromdb): {"tagName": {"list": [...], "total": N, ...}}
	// 路由策略:parseHistoryRecords 优先吃 IPage(包含 records 键)与裸数组两种形态;
	// 都不是再交 parseHistoryMap 吃 fromdb 的 map[tagName] 形态。
	if rows, ok := parseHistoryRecords(raw); ok {
		return rows, nil
	}
	if pts, ok := parseHistoryMap(raw); ok {
		return pts, nil
	}
	return nil, MapError(fmt.Errorf("历史值响应结构无法识别: %s", truncateForErr(raw, 200)))
}

// histPoint 历史点内部形态,共用于 IPage.records[] 与裸数组两种包装。
type histPoint struct {
	TagName  string          `json:"tagName"`
	TagValue json.RawMessage `json:"tagValue"`
	AppTime  string          `json:"appTime"`
	Quality  int             `json:"quality"`
}

func toHistoryRows(rows []histPoint) []HistoryRow {
	out := make([]HistoryRow, 0, len(rows))
	for _, r := range rows {
		out = append(out, HistoryRow{
			TagName: r.TagName, Value: r.TagValue,
			AppTime: r.AppTime, Quality: r.Quality,
		})
	}
	return out
}

// parseHistoryRecords 解析 /getHistoryValue 的 IPage 响应。
// 优先级:
//  1. IPage {"records": [...]}  — 真实契约
//  2. 裸数组 [...]               — 向后兼容(老实现 / 其它代理)
//
// records 为空数组或 null 视为"成功 + 0 条",仍返回 ([], true),不退回 map 解析器,
// 避免 fromdb 形态在解析器间反复兜底。
func parseHistoryRecords(raw json.RawMessage) ([]HistoryRow, bool) {
	s := bytes.TrimSpace(raw)
	if len(s) == 0 {
		return nil, false
	}

	// 形态 1:IPage {"records": [...]}
	if s[0] == '{' {
		var probe map[string]json.RawMessage
		if err := json.Unmarshal(raw, &probe); err != nil {
			return nil, false
		}
		if _, ok := probe["records"]; ok {
			var page struct {
				Records []histPoint `json:"records"`
			}
			if err := json.Unmarshal(raw, &page); err != nil {
				return nil, false
			}
			return toHistoryRows(page.Records), true
		}
		// 不是 IPage 形态,交给 map 解析器。
		return nil, false
	}

	// 形态 2:裸数组(向后兼容)
	if s[0] == '[' {
		var rows []histPoint
		if err := json.Unmarshal(raw, &rows); err != nil {
			return nil, false
		}
		return toHistoryRows(rows), true
	}

	return nil, false
}

// parseHistoryMap 解析 /getHistoryValueFromDB 的 {tagName: {list, total, ...}} 响应。
// 真实契约无 records 包装、字段为 tagValue(不是 value);空 map 视为"成功 + 0 条"。
func parseHistoryMap(raw json.RawMessage) ([]HistoryRow, bool) {
	s := bytes.TrimSpace(raw)
	if len(s) == 0 {
		return nil, false
	}
	if s[0] != '{' {
		return nil, false
	}
	var resp map[string]struct {
		List []struct {
			TagValue json.RawMessage `json:"tagValue"`
			TagTime  string          `json:"tagTime"`
			AppTime  string          `json:"appTime"`
			Quality  int             `json:"quality"`
		} `json:"list"`
	}
	if err := json.Unmarshal(raw, &resp); err != nil {
		return nil, false
	}
	out := make([]HistoryRow, 0)
	for name, slot := range resp {
		for _, p := range slot.List {
			out = append(out, HistoryRow{
				TagName: name, Value: p.TagValue,
				AppTime: firstNonEmpty(p.AppTime, p.TagTime),
				Quality: p.Quality,
			})
		}
	}
	return out, true
}

func firstNonEmpty(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

func truncateForErr(raw json.RawMessage, n int) string {
	s := string(raw)
	if len(s) <= n {
		return s
	}
	return s[:n] + "..."
}
