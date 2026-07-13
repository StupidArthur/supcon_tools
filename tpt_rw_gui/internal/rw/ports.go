package rw

import (
	"encoding/json"
	"time"

	"github.com/yzc/tpt_api"
)

// ClientPort 是 rw.Service 对 tptapi 客户端的最小依赖接口。
// 接口定义在消费方(rw 包),便于将来 mock;但当前唯一实现就是 *tptapi.TptClient,
// 由 internal/app/container.go 注入。避免预先造 adapter/ports 双向空壳。
type ClientPort interface {
	GetAllDsInfo() ([]tptapi.DsInfo, error)
	QueryTagsWithQuality(dsID *int, groupID, tagName, tagBaseName string,
		tagType, page, pageSize int, sort string) (json.RawMessage, error)
	GetRTValue(tagNames []string) ([]tptapi.RtValuePoint, error)
	WriteTagValues(values map[string]any) error
	GetHistoryValue(tagNames []string, begTime, endTime string,
		interval int, isSecond, isSource bool, offset, option int,
		page, pageSize int, sort string) (json.RawMessage, error)
	GetHistoryValueFromDB(tagNames []string, begTime, endTime string,
		isSource, numberToString bool, page, pageSize int, sort string) (json.RawMessage, error)

	// ListGroupTagsRaw 是空关键字 / 单 tagName 名查询时的退路:
	// 走 /tag-group/get (GroupID="0"),响应结构是 tagInfoList.records[],与 queryWithQuality 不同。
	// GroupID="0"=根分组。可在弹窗 input 不输入任何关键字时拉取整组下所有位号。
	// 注意:/tag-group/get 不支持 DS 过滤,platform 会返回所有数据源的位号。
	// service 层在 q.DSID 非 nil 时,在客户端按 tag.DSID 过滤(参见 Service.ListTags)。
	ListGroupTagsRaw(groupID, tagName string, tagType, page, pageSize int) (json.RawMessage, error)
}

// EnsureLoggedIn 用于 binding 调用前保证底层已登录。
// *tptapi.Service 暴露 Client() 自动续期。
type SessionPort interface {
	Client() *tptapi.TptClient
}

// TagListQuery 业务层传给 QueryTagsWithQuality 的查询条件。
type TagListQuery struct {
	DSID       *int   // nil = 不过滤
	GroupID    string // "" / "0" 表示根分组
	Keyword    string // 模糊匹配 tagName
	TagType    int    // 0 = 不过滤
	Page       int    // 默认 1
	PageSize   int    // 默认 200
	Sort       string // 默认 "-createTime"
}

// HistoryQuery 业务层传给 GetHistoryValue / FromDB 的查询条件。
type HistoryQuery struct {
	TagNames       []string
	BegTime        string
	EndTime        string
	Interval       int
	IsSecond       bool
	IsSource       bool
	Offset         int
	Option         int
	Page           int
	PageSize       int
	Sort           string
	Mode           Mode // Mode = "page"(默认) / "fromdb"
	NumberToString bool // 仅 FromDB 模式用
}

// Mode 历史值查询模式。
type Mode string

const (
	ModePage   Mode = "page"   // /getHistoryValue(IPage 分页)
	ModeFromDB Mode = "fromdb" // /getHistoryValueFromDB
)

// WriteRequest 写值入参。ReadbackDelayMs 0=不回读;>0=写后等指定毫秒再读一次。
type WriteRequest struct {
	Values         map[string]any
	ReadbackDelay  time.Duration // 0=不回读
	ReadbackTagNames []string    // 需要回读的位号名集合;空=回读 Values 全部
}
