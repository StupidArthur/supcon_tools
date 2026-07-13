package rw

import "encoding/json"

// DataSource 数据源(前端可见领域模型)。
//
// 字段直接源自 tptapi.DsInfo,但 Name 用 dsName(平台"显示名");type 字段以小写 subType 名统一。
type DataSource struct {
	ID        int    `json:"id"`
	Name      string `json:"name"`     // 平台 dsName
	URL       string `json:"url"`      // dsTarUrl
	Type      int    `json:"dsType"`
	SubType   int    `json:"dsSubType"`
	Alive     bool   `json:"alive"`
	DsStatus  int    `json:"dsStatus"`
}

// Tag 位号(含 quality 的 queryWithQuality 结果)。
//
// 实时值为 RawMessage,数据值原样保留(number/string/bool 等)。Quality 用 int:
//   0=Good;非零见平台约定(具体码值由 UI 解释)。
type Tag struct {
	ID           int             `json:"id"`
	Name         string          `json:"tagName"`      // = 平台 tagName
	BaseName     string          `json:"tagBaseName"`  // = 平台 tagBaseName
	TagType      int             `json:"tagType"`
	DSID         int             `json:"dsId"`
	DSName       string          `json:"dsName"`
	DataType     int             `json:"dataType"`
	DataTypeName string          `json:"dataTypeName"`
	TagValue     json.RawMessage `json:"tagValue,omitempty"`
	TagTime      string          `json:"tagTime"`
	Quality      int             `json:"quality"`
	GroupName    string          `json:"groupName"`
}

// RTValue 实时值点。Value 是 RawMessage,保留数字/字符串/布尔原类型。
type RTValue struct {
	TagName   string          `json:"tagName"`
	Value     json.RawMessage `json:"value"`
	TagTime   string          `json:"tagTime"`
	AppTime   string          `json:"appTime"`
	Quality   int             `json:"quality"`
	DataType  int             `json:"dataType"`
	DSID      int             `json:"dsId"`
	IsSuccess bool            `json:"isSuccess"`
	Message   string          `json:"message,omitempty"`
}

// WriteResult 写值结果,含回读。
type WriteResult struct {
	Written  []string         // 写入成功的 tagName 列表(按 WriteTagValues 平台的 failMsg 判定,本处不能直接拿,前端需对比回读)
	Readback []RTValue        // 写后回读的全部点
	Fails    map[string]string `json:"fails,omitempty"` // tagName -> 错误(从 readback 推断)
}

// HistoryRow 历史值行(已规整成 {tag, value, time, quality})。
type HistoryRow struct {
	TagName string          `json:"tagName"`
	Value   json.RawMessage `json:"value"`
	AppTime string          `json:"appTime"`
	Quality int             `json:"quality"`
}
