// Package bindings 是 Wails 边界层。按业务能力拆分(SessionBinding / RWBinding),
// 薄:仅做 DTO 转换 / 错误映射 / 调 Service。
//
// 业务包(session、rw)不 import 这个包,反之亦然。
package bindings

// DataSourceDTO 数据源(前端可见)。
type DataSourceDTO struct {
	ID        int    `json:"id"`
	Name      string `json:"name"`
	URL       string `json:"url"`
	Type      int    `json:"dsType"`
	SubType   int    `json:"dsSubType"`
	Alive     bool   `json:"alive"`
	DsStatus  int    `json:"dsStatus"`
}

// TagDTO 位号(含 quality)。
type TagDTO struct {
	ID           int             `json:"id"`
	Name         string          `json:"tagName"`
	BaseName     string          `json:"tagBaseName"`
	TagType      int             `json:"tagType"`
	DSID         int             `json:"dsId"`
	DSName       string          `json:"dsName"`
	DataType     int             `json:"dataType"`
	DataTypeName string          `json:"dataTypeName"`
	TagValue     string          `json:"tagValue,omitempty"`
	TagTime      string          `json:"tagTime"`
	Quality      int             `json:"quality"`
	GroupName    string          `json:"groupName"`
}

// RTValueDTO 实时值点。Value 用字符串(JSON 字面量)便于前端直接显示与比较。
type RTValueDTO struct {
	TagName   string `json:"tagName"`
	Value     string `json:"value"`
	TagTime   string `json:"tagTime"`
	AppTime   string `json:"appTime"`
	Quality   int    `json:"quality"`
	DataType  int    `json:"dataType"`
	DSID      int    `json:"dsId"`
	IsSuccess bool   `json:"isSuccess"`
	Message   string `json:"message,omitempty"`
}

// HistoryRowDTO 历史值行。
type HistoryRowDTO struct {
	TagName string `json:"tagName"`
	Value   string `json:"value"`
	AppTime string `json:"appTime"`
	Quality int    `json:"quality"`
}

// WriteRequestDTO 写值请求。
type WriteRequestDTO struct {
	Values          map[string]any `json:"values"`
	ReadbackDelayMs int            `json:"readbackDelayMs"` // 0=不回读
}

// WriteResultDTO 写值结果 + 回读。
type WriteResultDTO struct {
	Written  []string            `json:"written"`
	Fails    map[string]string   `json:"fails,omitempty"`
	Readback []RTValueDTO        `json:"readback,omitempty"`
}

// ListTagsRequestDTO 拉位号请求。
type ListTagsRequestDTO struct {
	DSID     *int   `json:"dsId,omitempty"` // nil 表示不过滤
	Keyword  string `json:"keyword"`
	Page     int    `json:"page"`
	PageSize int    `json:"pageSize"`
}

// ReadHistoryRequestDTO 读历史请求。
type ReadHistoryRequestDTO struct {
	TagNames []string `json:"tagNames"`
	BegTime  string   `json:"begTime"`
	EndTime  string   `json:"endTime"`
	Interval int      `json:"interval"`
	IsSecond bool     `json:"isSecond"`
	IsSource bool     `json:"isSource"`
	Offset   int      `json:"offset"`
	Option   int      `json:"option"`
	Page     int      `json:"page"`
	PageSize int      `json:"pageSize"`
	Sort     string   `json:"sort"`
	Mode     string   `json:"mode"` // "page" / "fromdb"
	NumberToString bool `json:"numberToString"`
}

// PublicErrorDTO 前端可见错误。
type PublicErrorDTO struct {
	Code    string `json:"code"`
	Message string `json:"message"`
	Kind    string `json:"kind"`
}

// Error 让 *PublicErrorDTO 满足 error 接口(Wails 生成签名要求 error,而不是 struct)。
func (e *PublicErrorDTO) Error() string {
	if e.Code != "" {
		return "[" + e.Kind + ":" + e.Code + "] " + e.Message
	}
	return "[" + e.Kind + "] " + e.Message
}
