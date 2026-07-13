package bindings

import (
	"context"
	"encoding/json"
	"time"

	"tpt_rw_gui/internal/rw"
	"tpt_rw_gui/internal/session"
)

// RWBinding 暴露给前端的"值读写"业务方法。薄:仅 DTO 转换 + 错误映射 + 调 Service。
type RWBinding struct {
	ctx context.Context
	sess *session.Service
	svc *rw.Service
}

// NewRWBinding 创建 RWBinding。
func NewRWBinding(sess *session.Service, svc *rw.Service) *RWBinding {
	return &RWBinding{sess: sess, svc: svc}
}

// SetContext 由 Lifecycle.Startup 注入应用根 ctx。
func (b *RWBinding) SetContext(ctx context.Context) { b.ctx = ctx }

// ListDataSources 拉数据源列表。
func (b *RWBinding) ListDataSources() ([]DataSourceDTO, error) {
	if b.ctx == nil {
		b.ctx = context.Background()
	}
	srcs, err := b.svc.ListDataSources(b.ctx)
	if err != nil {
		return nil, mapErr(err)
	}
	out := make([]DataSourceDTO, 0, len(srcs))
	for _, d := range srcs {
		out = append(out, DataSourceDTO{
			ID: d.ID, Name: d.Name, URL: d.URL,
			Type: d.Type, SubType: d.SubType,
			Alive: d.Alive, DsStatus: d.DsStatus,
		})
	}
	return out, nil
}

// ListTags 经 queryWithQuality 拉位号。
// 注:err 路径返回 (non-nil empty slice, mappedErr) — 避免 Wails 把 Go nil slice
// 序列化成 JSON null,导致前端 `arr[0]` 触发 TypeError。
func (b *RWBinding) ListTags(req ListTagsRequestDTO) ([]TagDTO, error) {
	if b.ctx == nil {
		b.ctx = context.Background()
	}
	tags, err := b.svc.ListTags(b.ctx, rw.TagListQuery{
		DSID: req.DSID, GroupID: "0",
		Keyword: req.Keyword, Page: req.Page, PageSize: req.PageSize,
	})
	mapped := mapErr(err)
	out := make([]TagDTO, 0, len(tags))
	for _, t := range tags {
		out = append(out, TagDTO{
			ID: t.ID, Name: t.Name, BaseName: t.BaseName,
			TagType: t.TagType, DSID: t.DSID, DSName: t.DSName,
			DataType: t.DataType, DataTypeName: t.DataTypeName,
			TagValue: rawToString(t.TagValue),
			TagTime: t.TagTime, Quality: t.Quality, GroupName: t.GroupName,
		})
	}
	return out, mapped
}

// ReadRealtime 按位号名读实时值。
func (b *RWBinding) ReadRealtime(tagNames []string) ([]RTValueDTO, error) {
	if b.ctx == nil {
		b.ctx = context.Background()
	}
	pts, err := b.svc.ReadRealtime(b.ctx, tagNames)
	mapped := mapErr(err)
	out := make([]RTValueDTO, 0, len(pts))
	for _, p := range pts {
		out = append(out, RTValueDTO{
			TagName: p.TagName, Value: rawToString(p.Value),
			TagTime: p.TagTime, AppTime: p.AppTime,
			Quality: p.Quality, DataType: p.DataType, DSID: p.DSID,
			IsSuccess: p.IsSuccess, Message: p.Message,
		})
	}
	return out, mapped
}

// WriteValues 写值(+ 可选回读)。
func (b *RWBinding) WriteValues(req WriteRequestDTO) (WriteResultDTO, error) {
	if b.ctx == nil {
		b.ctx = context.Background()
	}
	var delay time.Duration
	if req.ReadbackDelayMs > 0 {
		delay = time.Duration(req.ReadbackDelayMs) * time.Millisecond
	}
	res, err := b.svc.WriteValues(b.ctx, rw.WriteRequest{
		Values: req.Values, ReadbackDelay: delay,
	})
	mapped := mapErr(err)
	if mapped != nil {
		return WriteResultDTO{}, mapped
	}
	out := WriteResultDTO{}
	if res != nil {
		out.Written = res.Written
		out.Fails = res.Fails
		// Readback slice 显式 non-nil empty,避免 Wails JSON null 化
		out.Readback = make([]RTValueDTO, 0, len(res.Readback))
		for _, r := range res.Readback {
			out.Readback = append(out.Readback, RTValueDTO{
				TagName: r.TagName, Value: rawToString(r.Value),
				TagTime: r.TagTime, AppTime: r.AppTime,
				Quality: r.Quality, DataType: r.DataType, DSID: r.DSID,
				IsSuccess: r.IsSuccess, Message: r.Message,
			})
		}
	} else {
		out.Readback = make([]RTValueDTO, 0)
	}
	return out, nil
}

// ReadHistory 读历史值(Mode: "page"=IPage / "fromdb"=GetHistoryValueFromDB)。
func (b *RWBinding) ReadHistory(req ReadHistoryRequestDTO) ([]HistoryRowDTO, error) {
	if b.ctx == nil {
		b.ctx = context.Background()
	}
	rows, err := b.svc.ReadHistory(b.ctx, rw.HistoryQuery{
		TagNames: req.TagNames, BegTime: req.BegTime, EndTime: req.EndTime,
		Interval: req.Interval, IsSecond: req.IsSecond, IsSource: req.IsSource,
		Offset: req.Offset, Option: req.Option,
		Page: req.Page, PageSize: req.PageSize, Sort: req.Sort,
		Mode: rw.Mode(req.Mode), NumberToString: req.NumberToString,
	})
	mapped := mapErr(err)
	out := make([]HistoryRowDTO, 0, len(rows))
	for _, r := range rows {
		out = append(out, HistoryRowDTO{
			TagName: r.TagName, Value: rawToString(r.Value),
			AppTime: r.AppTime, Quality: r.Quality,
		})
	}
	return out, mapped
}

// mapErr 把 *rw.PublicError 翻成 DTO 友好的 *PublicErrorDTO。
// Kind="data"(位号不存在这类"语义空"错误)在 binding 层视为 nil error,
// 这样前端拿到空切片而非 toast 红字。
func mapErr(err error) error {
	if err == nil {
		return nil
	}
	if pe, ok := err.(*rw.PublicError); ok {
		if pe.Kind == rw.KindData {
			// 数据空,让前端拿到空响应;不算 error
			return nil
		}
		return &PublicErrorDTO{Code: pe.Code, Message: pe.Message, Kind: pe.Kind}
	}
	return &PublicErrorDTO{Message: err.Error(), Kind: "api"}
}

// rawToString json.RawMessage -> 可读字符串(JSON 字面量)。
// nil/"null" 返回 "";其它原样。
func rawToString(raw json.RawMessage) string {
	if len(raw) == 0 {
		return ""
	}
	s := string(raw)
	if s == "null" {
		return ""
	}
	return s
}
