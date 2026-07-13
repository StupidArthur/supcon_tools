package bindings

import (
	"context"
	"encoding/json"
	"sync"
	"testing"
	"time"

	"github.com/yzc/tpt_api"

	"tpt_rw_gui/internal/rw"
	"tpt_rw_gui/internal/session"
)

// stub RW client,同 rw_internal_test.go 的 fakeClient 思路,但减少维护开销。
type stubPort struct {
	mu        sync.Mutex
	ds        []tptapi.DsInfo
	tags      []rw.Tag
	rt        map[string][]tptapi.RtValuePoint
	written   map[string]any
	histRecs  json.RawMessage
	histMap   json.RawMessage
	histMode  rw.Mode
	listCalls int
}

func (s *stubPort) GetAllDsInfo() ([]tptapi.DsInfo, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.listCalls++
	return s.ds, nil
}
func (s *stubPort) QueryTagsWithQuality(_ *int, _, _, _ string, _ int, _, _ int, _ string) (json.RawMessage, error) {
	return json.RawMessage(`[{"id":1,"tagName":"demo.t_double","tagBaseName":"1_demo.t_double","dataType":11,"tagType":1,"dsId":9,"tagValue":3.14,"tagTime":"2026-07-13 12:00:00","quality":0,"groupName":"Root"}]`), nil
}
func (s *stubPort) GetRTValue(names []string) ([]tptapi.RtValuePoint, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var out []tptapi.RtValuePoint
	for _, n := range names {
		out = append(out, s.rt[n]...)
	}
	return out, nil
}
func (s *stubPort) WriteTagValues(values map[string]any) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.written == nil {
		s.written = map[string]any{}
	}
	for k, v := range values {
		s.written[k] = v
	}
	return nil
}
func (s *stubPort) GetHistoryValue(_ []string, _, _ string, _ int, _, _ bool, _, _ int, _, _ int, _ string) (json.RawMessage, error) {
	s.histMode = rw.ModePage
	return s.histRecs, nil
}
func (s *stubPort) GetHistoryValueFromDB(_ []string, _, _ string, _, _ bool, _, _ int, _ string) (json.RawMessage, error) {
	s.histMode = rw.ModeFromDB
	return s.histMap, nil
}

// fakeAdapter 把 *stubPort 暴露成 ClientPort。
type fakeAdapter struct{ p *stubPort }

func (f *fakeAdapter) GetAllDsInfo() ([]tptapi.DsInfo, error) { return f.p.GetAllDsInfo() }
func (f *fakeAdapter) QueryTagsWithQuality(dsID *int, groupID, tagName, tagBaseName string, tagType, page, pageSize int, sort string) (json.RawMessage, error) {
	return f.p.QueryTagsWithQuality(dsID, groupID, tagName, tagBaseName, tagType, page, pageSize, sort)
}
func (f *fakeAdapter) GetRTValue(tagNames []string) ([]tptapi.RtValuePoint, error) {
	return f.p.GetRTValue(tagNames)
}
func (f *fakeAdapter) WriteTagValues(values map[string]any) error { return f.p.WriteTagValues(values) }
func (f *fakeAdapter) GetHistoryValue(tagNames []string, begTime, endTime string, interval int, isSecond, isSource bool, offset, option int, page, pageSize int, sort string) (json.RawMessage, error) {
	return f.p.GetHistoryValue(tagNames, begTime, endTime, interval, isSecond, isSource, offset, option, page, pageSize, sort)
}
func (f *fakeAdapter) GetHistoryValueFromDB(tagNames []string, begTime, endTime string, isSource, numberToString bool, page, pageSize int, sort string) (json.RawMessage, error) {
	return f.p.GetHistoryValueFromDB(tagNames, begTime, endTime, isSource, numberToString, page, pageSize, sort)
}
func (f *fakeAdapter) ListGroupTagsRaw(_, _ string, _, _, _ int) (json.RawMessage, error) {
	return f.p.GetHistoryValueFromDB(nil, "", "", false, false, 0, 0, "") // 占位;binding test 不经此路径
}

func newBinding(t *testing.T) (*RWBinding, *stubPort) {
	t.Helper()
	stub := &stubPort{
		ds: []tptapi.DsInfo{{ID: 1, DsName: "opcua-sim", DsTarUrl: "opc.tcp://h:18950", Alive: true}},
		rt: map[string][]tptapi.RtValuePoint{
			"demo.t_double": {{TagName: "demo.t_double", TagValue: json.RawMessage(`3.14`), IsSuccess: true}},
		},
		histRecs: json.RawMessage(`[{"tagName":"a","tagValue":1.0,"appTime":"2026-01-01 00:00:00","quality":0}]`),
		histMap:  json.RawMessage(`[{"tagName":"b","tagValue":2.0,"appTime":"2026-01-02 00:00:00","quality":0}]`),
	}
	port := rw.NewService(&fakeAdapter{p: stub})
	sess := session.NewService(nil)
	sess.MarkLoggedInForTest("http://test")
	binding := NewRWBinding(sess, port)
	binding.SetContext(context.Background())
	return binding, stub
}

func TestRW_LoggedOut_ReturnsAuthError(t *testing.T) {
	stub := &stubPort{rt: map[string][]tptapi.RtValuePoint{}}
	port := rw.NewService(&fakeAdapter{p: stub})
	sess := session.NewService(nil)
	binding := NewRWBinding(sess, port)
	binding.SetContext(context.Background())

	assertAuth := func(name string, err error) {
		t.Helper()
		pe, ok := err.(*PublicErrorDTO)
		if !ok || pe.Kind != "auth" {
			t.Fatalf("%s want auth error, got %T %v", name, err, err)
		}
	}

	_, err := binding.ListDataSources()
	assertAuth("ListDataSources", err)
	_, err = binding.ListTags(ListTagsRequestDTO{})
	assertAuth("ListTags", err)
	_, err = binding.ReadRealtime(nil)
	assertAuth("ReadRealtime", err)
	_, err = binding.WriteValues(WriteRequestDTO{})
	assertAuth("WriteValues", err)
	_, err = binding.ReadHistory(ReadHistoryRequestDTO{})
	assertAuth("ReadHistory", err)

	if stub.listCalls != 0 {
		t.Fatalf("stub should not be called when logged out, got %d calls", stub.listCalls)
	}
}

func TestRW_ListDataSources(t *testing.T) {
	b, _ := newBinding(t)
	got, err := b.ListDataSources()
	if err != nil {
		t.Fatalf("ListDataSources: %v", err)
	}
	if len(got) != 1 || got[0].Name != "opcua-sim" {
		t.Fatalf("want 1 ds named opcua-sim, got %+v", got)
	}
}

func TestRW_ListTags(t *testing.T) {
	b, _ := newBinding(t)
	got, err := b.ListTags(ListTagsRequestDTO{Keyword: "demo"})
	if err != nil {
		t.Fatalf("ListTags: %v", err)
	}
	if len(got) != 1 || got[0].Name != "demo.t_double" {
		t.Fatalf("want 1 tag, got %+v", got)
	}
	if got[0].TagValue != "3.14" {
		t.Fatalf("want TagValue \"3.14\", got %q", got[0].TagValue)
	}
}

func TestRW_ReadRealtime(t *testing.T) {
	b, _ := newBinding(t)
	pts, err := b.ReadRealtime([]string{"demo.t_double"})
	if err != nil {
		t.Fatalf("ReadRealtime: %v", err)
	}
	if len(pts) != 1 || pts[0].Value != "3.14" {
		t.Fatalf("want 1 RTValue 3.14, got %+v", pts)
	}
}

// Phase: RED — 期望 binding.ReadRealtime 在 RT 抛 *tptapi.TptAPIError{Code:"500",Msg:"Tag Dose Not Exist"}
// 时返回 ([]RTValueDTO{}, nil) — 关键修复:Wails 序列化 Go nil slice 成 JSON null,
// 导致前端 `list[0]` 抛 TypeError。binding 应当保证 slice 非 nil 且 empty。
func TestRW_ReadRealtime_NonExistentTag_ReturnsEmptySlice(t *testing.T) {
	b := newNonExistentBinding(t)
	pts, err := b.ReadRealtime([]string{"absent.tag"})
	if err != nil {
		t.Fatalf("ReadRealtime: 期望 nil error(平台 500+Tag Dose Not Exist 视为数据空),得 %v", err)
	}
	if pts == nil {
		t.Fatalf("ReadRealtime: 返回 nil slice 而非空 slice — 前端会 TypeError")
	}
	if len(pts) != 0 {
		t.Fatalf("ReadRealtime: 期望 0 条,得 %d 条: %+v", len(pts), pts)
	}
}

func TestRW_WriteValues_WithReadback(t *testing.T) {
	b, stub := newBinding(t)
	res, err := b.WriteValues(WriteRequestDTO{
		Values:          map[string]any{"demo.t_double": 7.5},
		ReadbackDelayMs: 5, // 极短,避免 sleep
	})
	if err != nil {
		t.Fatalf("WriteValues: %v", err)
	}
	if stub.written["demo.t_double"] != 7.5 {
		t.Fatalf("written map want 7.5, got %v", stub.written["demo.t_double"])
	}
	if len(res.Readback) != 1 || res.Readback[0].Value != "3.14" {
		t.Fatalf("readback want [3.14], got %+v", res.Readback)
	}
}

// mapErr 在 Kind:"data"(位号不存在)时应当返回 nil,
// 这样前端 ReadRealtime 拿到的就是空切片(不弹 toast)。
func TestMapErr_DataKindReturnsNil(t *testing.T) {
	pe := &rw.PublicError{Code: "500", Message: "Tag Dose Not Exist", Kind: rw.KindData}
	if err := mapErr(pe); err != nil {
		t.Fatalf("mapErr should swallow data kind, got %T %v", err, err)
	}
	// 其它 Kind 仍应返回 error。
	authPE := &rw.PublicError{Code: "A0230", Message: "登录已超时", Kind: "auth"}
	if err := mapErr(authPE); err == nil {
		t.Fatalf("auth kind should still error")
	}
}

// newNonExistentBinding 构造一个 binding,底层 stub 的 GetRTValue 返回
// *tptapi.TptAPIError{Code:"500",Msg:"Tag Dose Not Exist"}。
// 复现线上场景:平台 RT 路径"位号不存在"语义。
func newNonExistentBinding(t *testing.T) *RWBinding {
	t.Helper()
	stub := &stubPort{}
	port := &nonexistentAdapter{stub: stub}
	svc := rw.NewService(port)
	sess := session.NewService(nil)
	sess.MarkLoggedInForTest("http://test")
	binding := NewRWBinding(sess, svc)
	binding.SetContext(context.Background())
	return binding
}

// nonexistentAdapter 把 stubPort 的 GetRTValue 替换为返"位号不存在"业务错误。
// 其它方法委托给 stub (不起作用,只是满足 ClientPort 接口)。
type nonexistentAdapter struct{ stub *stubPort }

func (a *nonexistentAdapter) GetAllDsInfo() ([]tptapi.DsInfo, error) {
	return a.stub.GetAllDsInfo()
}
func (a *nonexistentAdapter) QueryTagsWithQuality(dsID *int, groupID, tagName, tagBaseName string, tagType, page, pageSize int, sort string) (json.RawMessage, error) {
	return a.stub.QueryTagsWithQuality(dsID, groupID, tagName, tagBaseName, tagType, page, pageSize, sort)
}
func (a *nonexistentAdapter) GetRTValue(tagNames []string) ([]tptapi.RtValuePoint, error) {
	return nil, &tptapi.TptAPIError{Code: "500", Msg: "Tag Dose Not Exist"}
}
func (a *nonexistentAdapter) WriteTagValues(values map[string]any) error {
	return a.stub.WriteTagValues(values)
}
func (a *nonexistentAdapter) GetHistoryValue(tagNames []string, begTime, endTime string, interval int, isSecond, isSource bool, offset, option int, page, pageSize int, sort string) (json.RawMessage, error) {
	return a.stub.GetHistoryValue(tagNames, begTime, endTime, interval, isSecond, isSource, offset, option, page, pageSize, sort)
}
func (a *nonexistentAdapter) GetHistoryValueFromDB(tagNames []string, begTime, endTime string, isSource, numberToString bool, page, pageSize int, sort string) (json.RawMessage, error) {
	return a.stub.GetHistoryValueFromDB(tagNames, begTime, endTime, isSource, numberToString, page, pageSize, sort)
}
func (a *nonexistentAdapter) ListGroupTagsRaw(_ string, _ string, _, _, _ int) (json.RawMessage, error) {
	return nil, nil
}

func TestRW_ReadHistory_ModeRoute(t *testing.T) {
	b, stub := newBinding(t)
	_, err := b.ReadHistory(ReadHistoryRequestDTO{
		TagNames: []string{"a"}, BegTime: "2026-01-01 00:00:00", EndTime: "2026-01-02 00:00:00",
		Mode: "page",
	})
	if err != nil {
		t.Fatalf("ReadHistory page: %v", err)
	}
	if stub.histMode != rw.ModePage {
		t.Fatalf("want page, got %s", stub.histMode)
	}
	_, err = b.ReadHistory(ReadHistoryRequestDTO{
		TagNames: []string{"a"}, BegTime: "2026-01-01 00:00:00", EndTime: "2026-01-02 00:00:00",
		Mode: "fromdb",
	})
	if err != nil {
		t.Fatalf("ReadHistory fromdb: %v", err)
	}
	if stub.histMode != rw.ModeFromDB {
		t.Fatalf("want fromdb, got %s", stub.histMode)
	}
}

// 防 "imported and not used" 警告。
var _ = time.Second
