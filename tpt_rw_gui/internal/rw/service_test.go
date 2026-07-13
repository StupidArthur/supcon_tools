package rw

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/yzc/tpt_api"
)

// fakeClient 实现 ClientPort,产出固定 fixture 数据。
type fakeClient struct {
	mu      sync.Mutex
	dsList  []tptapi.DsInfo
	rtList  map[string][]tptapi.RtValuePoint
	rawHist json.RawMessage
	histMode Mode
	calls   int
}

func (f *fakeClient) GetAllDsInfo() ([]tptapi.DsInfo, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls++
	return f.dsList, nil
}

func (f *fakeClient) QueryTagsWithQuality(dsID *int, groupID, tagName, tagBaseName string,
	tagType, page, pageSize int, sort string) (json.RawMessage, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls++
	return json.RawMessage(`{"records":[{"id":1,"tagName":"` + tagName + `","tagBaseName":"1_` + tagName + `","dataType":11,"tagType":1,"dsId":9,"tagValue":3.14,"tagTime":"2026-07-13 12:00:00","quality":0,"groupName":"Root"}]}`), nil
}

func (f *fakeClient) GetRTValue(tagNames []string) ([]tptapi.RtValuePoint, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls++
	out := make([]tptapi.RtValuePoint, 0, len(tagNames))
	for _, n := range tagNames {
		if pts, ok := f.rtList[n]; ok {
			out = append(out, pts...)
		}
	}
	return out, nil
}

func (f *fakeClient) WriteTagValues(values map[string]any) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls++
	return nil
}

func (f *fakeClient) GetHistoryValue(_ []string, _ string, _ string,
	_ int, _, _ bool, _, _ int, _, _ int, _ string) (json.RawMessage, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.histMode = ModePage
	f.calls++
	return f.rawHist, nil
}

func (f *fakeClient) GetHistoryValueFromDB(_ []string, _ string, _ string,
	_, _ bool, _, _ int, _ string) (json.RawMessage, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.histMode = ModeFromDB
	f.calls++
	return f.rawHist, nil
}

func (f *fakeClient) ListGroupTagsRaw(_, _ string, _, _, _ int) (json.RawMessage, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls++
	return f.rawHist, nil
}

func TestListDataSources_MapsFields(t *testing.T) {
	fc := &fakeClient{
		dsList: []tptapi.DsInfo{
			{ID: 9, DsName: "opcua-sim", DsTarUrl: "opc.tcp://localhost:18950", DsType: 1, DsSubType: 4, Alive: true},
		},
	}

	s := NewService(fc)
	got, err := s.ListDataSources(context.Background())
	if err != nil {
		t.Fatalf("ListDataSources: %v", err)
	}
	if len(got) != 1 {
		t.Fatalf("want 1 ds, got %d", len(got))
	}
	if got[0].Name != "opcua-sim" {
		t.Fatalf("Name want opcua-sim, got %q", got[0].Name)
	}
	if got[0].URL != "opc.tcp://localhost:18950" {
		t.Fatalf("URL want opc.tcp://..., got %q", got[0].URL)
	}
	if !got[0].Alive {
		t.Fatalf("Alive want true")
	}
}

func TestListTags_RoutesQuery(t *testing.T) {
	fc := &fakeClient{}
	s := NewService(fc)
	got, err := s.ListTags(context.Background(), TagListQuery{Keyword: "demo", GroupID: "0"})
	if err != nil {
		t.Fatalf("ListTags: %v", err)
	}
	if len(got) != 1 || got[0].Name != "demo" {
		t.Fatalf("want 1 tag named demo, got %+v", got)
	}
}

func TestListTags_ParsesBareArray(t *testing.T) {
	fc := &rawClient{resp: json.RawMessage(`[{"id":1,"tagName":"x","tagBaseName":"1_x","dataType":11,"tagType":1,"dsId":9,"dataTypeName":"","groupName":"Root"}]`)}
	s := NewService(fc)
	got, err := s.ListTags(context.Background(), TagListQuery{GroupID: "0"})
	if err != nil {
		t.Fatalf("bare array: %v", err)
	}
	if len(got) != 1 || got[0].Name != "x" {
		t.Fatalf("want 1 tag named x, got %+v", got)
	}
}

func TestListTags_ParsesDataAlias(t *testing.T) {
	fc := &rawClient{resp: json.RawMessage(`{"data":[{"id":2,"tagName":"y","tagBaseName":"1_y","dataType":11,"tagType":1,"dsId":9,"dataTypeName":"","groupName":"Root"}]}`)}
	s := NewService(fc)
	got, err := s.ListTags(context.Background(), TagListQuery{GroupID: "0"})
	if err != nil {
		t.Fatalf("data alias: %v", err)
	}
	if len(got) != 1 || got[0].Name != "y" {
		t.Fatalf("want 1 tag named y, got %+v", got)
	}
}

// 历史 bug 复现:平台返回 dict 但没有任何 records/data/list 字段,旧实现会到裸数组分支报错。
// 现在应解析为空数组,不应有错。
func TestListTags_DictWithoutKnownKeys_Ok(t *testing.T) {
	fc := &rawClient{resp: json.RawMessage(`{"total":0,"size":10,"current":1,"pages":0}`)}
	s := NewService(fc)
	got, err := s.ListTags(context.Background(), TagListQuery{GroupID: "0"})
	if err != nil {
		t.Fatalf("dict without keys: %v", err)
	}
	if len(got) != 0 {
		t.Fatalf("want empty, got %+v", got)
	}
}

func TestListTags_InvalidJSON(t *testing.T) {
	fc := &rawClient{resp: json.RawMessage(`not-json`)}
	s := NewService(fc)
	_, err := s.ListTags(context.Background(), TagListQuery{GroupID: "0"})
	if err == nil {
		t.Fatalf("want error on invalid json")
	}
}

func TestListTags_EmptyResponse(t *testing.T) {
	fc := &rawClient{resp: json.RawMessage(`null`)}
	s := NewService(fc)
	got, err := s.ListTags(context.Background(), TagListQuery{GroupID: "0"})
	if err != nil {
		t.Fatalf("null: %v", err)
	}
	if len(got) != 0 {
		t.Fatalf("want empty, got %+v", got)
	}
}

// 空关键字应当走 /tag-group/get 而不是 queryWithQuality(后者在 tagName="" 上可能返 0 条)
// 响应是 tagInfoList.records[] 形态;正确解析出 2 条。
func TestListTags_EmptyKeyword_RoutesToGroupTags(t *testing.T) {
	fc := &rawClient{
		resp: json.RawMessage(`{"tagInfoList":{"records":[{"id":10,"tagName":"demo.x","tagBaseName":"1_demo.x","dataType":11,"tagType":1,"dsId":9,"dataTypeName":"","groupName":"Root"},{"id":11,"tagName":"demo.y","tagBaseName":"1_demo.y","dataType":11,"tagType":1,"dsId":9,"dataTypeName":"","groupName":"Root"}]}}`),
	}
	s := NewService(fc)
	got, err := s.ListTags(context.Background(), TagListQuery{Keyword: "", GroupID: "0"})
	if err != nil {
		t.Fatalf("empty-keyword groupTags: %v", err)
	}
	if fc.groupTagsCalls != 1 {
		t.Fatalf("want 1 groupTags call, got %d (queryCalls=%d)", fc.groupTagsCalls, fc.queryCalls)
	}
	if fc.queryCalls != 0 {
		t.Fatalf("want 0 queryWithQuality calls when keyword empty, got %d", fc.queryCalls)
	}
	if len(got) != 2 || got[0].Name != "demo.x" || got[1].Name != "demo.y" {
		t.Fatalf("want 2 tags, got %+v", got)
	}
}

// 非空关键字仍走 queryWithQuality(空 keyword fallback 不能把"用户输了关键字"的请求误打去别处)。
func TestListTags_NonEmptyKeyword_RoutesToQuery(t *testing.T) {
	fc := &rawClient{
		resp: json.RawMessage(`[{"id":1,"tagName":"x","tagBaseName":"1_x","dataType":11,"tagType":1,"dsId":9,"dataTypeName":"","groupName":"Root"}]`),
	}
	s := NewService(fc)
	got, err := s.ListTags(context.Background(), TagListQuery{Keyword: "x", GroupID: "0"})
	if err != nil {
		t.Fatalf("non-empty keyword: %v", err)
	}
	if fc.queryCalls != 1 {
		t.Fatalf("want 1 queryWithQuality call, got %d", fc.queryCalls)
	}
	if fc.groupTagsCalls != 0 {
		t.Fatalf("want 0 groupTags calls, got %d", fc.groupTagsCalls)
	}
	if len(got) != 1 {
		t.Fatalf("want 1 tag, got %+v", got)
	}
}

// rawClient 让测试精度控制响应。
type rawClient struct {
	resp json.RawMessage
	// 区分调用了哪个端点(空关键字→groupTags,非空→queryWithQuality)
	groupTagsCalls int
	queryCalls     int
}

func (c *rawClient) GetAllDsInfo() ([]tptapi.DsInfo, error) { return nil, nil }
func (c *rawClient) QueryTagsWithQuality(dsID *int, groupID, tagName, tagBaseName string,
	tagType, page, pageSize int, sort string) (json.RawMessage, error) {
	c.queryCalls++
	return c.resp, nil
}
func (c *rawClient) GetRTValue(tagNames []string) ([]tptapi.RtValuePoint, error) { return nil, nil }
func (c *rawClient) WriteTagValues(values map[string]any) error               { return nil }
func (c *rawClient) GetHistoryValue(_ []string, _ string, _ string,
	_ int, _, _ bool, _, _ int, _, _ int, _ string) (json.RawMessage, error) {
	return nil, nil
}
func (c *rawClient) GetHistoryValueFromDB(_ []string, _ string, _ string,
	_, _ bool, _, _ int, _ string) (json.RawMessage, error) {
	return nil, nil
}
func (c *rawClient) ListGroupTagsRaw(_, _ string, _, _, _ int) (json.RawMessage, error) {
	c.groupTagsCalls++
	return c.resp, nil
}

func TestReadRealtime_ReturnsPoints(t *testing.T) {
	fc := &fakeClient{
		rtList: map[string][]tptapi.RtValuePoint{
			"demo.t_double": {{TagName: "demo.t_double", TagValue: json.RawMessage(`3.14`), Quality: 0, DataType: 11, IsSuccess: true}},
		},
	}
	s := NewService(fc)
	got, err := s.ReadRealtime(context.Background(), []string{"demo.t_double"})
	if err != nil {
		t.Fatalf("ReadRealtime: %v", err)
	}
	if len(got) != 1 || got[0].TagName != "demo.t_double" {
		t.Fatalf("want 1 point, got %+v", got)
	}
}

func TestWriteValues_WithReadback_Succeeds(t *testing.T) {
	fc := &fakeClient{
		rtList: map[string][]tptapi.RtValuePoint{
			"demo.w": {{TagName: "demo.w", TagValue: json.RawMessage(`7.5`), Quality: 0, IsSuccess: true}},
		},
	}
	s := NewService(fc)
	res, err := s.WriteValues(context.Background(), WriteRequest{
		Values:        map[string]any{"demo.w": 7.5},
		ReadbackDelay: 5 * time.Millisecond, // 测试不要 sleep 1s
	})
	if err != nil {
		t.Fatalf("WriteValues: %v", err)
	}
	if res == nil || len(res.Readback) != 1 {
		t.Fatalf("want 1 readback, got %+v", res)
	}
}

func TestReadHistory_RouteByMode(t *testing.T) {
	histRecords := json.RawMessage(`[{"tagName":"a","tagValue":1.0,"appTime":"2026-07-13 00:00:00","quality":0}]`)
	fc := &fakeClient{rawHist: histRecords}
	s := NewService(fc)
	got, err := s.ReadHistory(context.Background(), HistoryQuery{
		TagNames: []string{"a"}, BegTime: "2026-07-01 00:00:00", EndTime: "2026-07-13 23:59:59",
		Mode: ModePage,
	})
	if err != nil {
		t.Fatalf("ReadHistory page: %v", err)
	}
	if len(got) != 1 || got[0].TagName != "a" {
		t.Fatalf("want 1 history row, got %+v", got)
	}
	if fc.histMode != ModePage {
		t.Fatalf("mode want page, got %q", fc.histMode)
	}
	// 切到 FromDB
	_, err = s.ReadHistory(context.Background(), HistoryQuery{
		TagNames: []string{"a"}, BegTime: "2026-07-01 00:00:00", EndTime: "2026-07-13 23:59:59",
		Mode: ModeFromDB,
	})
	if err != nil {
		t.Fatalf("ReadHistory fromdb: %v", err)
	}
	if fc.histMode != ModeFromDB {
		t.Fatalf("mode want fromdb, got %q", fc.histMode)
	}
}

func TestMapError_AuthCode(t *testing.T) {
	e := &tptapi.TptAPIError{Code: "A0230", Msg: "登录已超时"}
	got := MapError(e)
	if got.Kind != "auth" {
		t.Fatalf("want auth, got %q", got.Kind)
	}
}

func TestMapError_Nil(t *testing.T) {
	if MapError(nil) != nil {
		t.Fatalf("MapError(nil) should be nil")
	}
}

func TestMapError_Parse(t *testing.T) {
	got := MapError(fmt.Errorf("响应非 JSON: <html>"))
	if got.Kind != "parse" {
		t.Fatalf("want parse, got %q", got.Kind)
	}
}

// 平台在 RT / 历史 路径上对不存在位号:HTTP 200 + body {code:"500", msg:"Tag Dose Not Exist"}。
// 这应当归类为 Kind:"data"(语义空,不算平台错误)。
func TestMapError_NonExistentTag(t *testing.T) {
	e := &tptapi.TptAPIError{Code: "500", Msg: "Tag Dose Not Exist"}
	got := MapError(e)
	if got.Kind != KindData {
		t.Fatalf("want %q, got %q (msg=%q)", KindData, got.Kind, got.Message)
	}
	if got.Code != "500" {
		t.Fatalf("want code 500, got %q", got.Code)
	}
}

// 拼写 typo 兜底:"Does Not" 也识别。
func TestMapError_NonExistentTag_TypoFallback(t *testing.T) {
	e := &tptapi.TptAPIError{Code: "500", Msg: "Tag Does Not Exist"}
	got := MapError(e)
	if got.Kind != KindData {
		t.Fatalf("want %q (typo fallback), got %q", KindData, got.Kind)
	}
}

// 500 但不是位号缺失 → 仍走 api。
func TestMapError_500OtherMessage_NotData(t *testing.T) {
	e := &tptapi.TptAPIError{Code: "500", Msg: "Internal Server Error"}
	got := MapError(e)
	if got.Kind == KindData {
		t.Fatalf("500+内部错不应被识别为 data,got %q", got.Kind)
	}
	if got.Kind != "api" {
		t.Fatalf("want api, got %q", got.Kind)
	}
}

// 非 500 不要被识别为 data。
func TestMapError_OtherCode_NotData(t *testing.T) {
	e := &tptapi.TptAPIError{Code: "A0400", Msg: "Tag Dose Not Exist"}
	got := MapError(e)
	if got.Kind == KindData {
		t.Fatalf("A0400 不应被识别为 data")
	}
}
