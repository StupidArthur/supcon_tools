package rw

import (
	"encoding/json"

	"github.com/yzc/tpt_api"
)

// TptClientAdapter 把 *tptapi.Service 适配成 ClientPort。
//
// 每次方法调用都通过 .Client() 拿当前 *tptapi.TptClient(其内部 5min JWT 续期 + 失败用旧 client
// 重试机制,tptapi.Service.Client() 行为,见 tpt_api/go/state_full.go:49)。
type TptClientAdapter struct {
	Svc *tptapi.Service
}

// NewTptClientAdapter 创建 adapter。svc 在登录后已持有底层 TptClient。
func NewTptClientAdapter(svc *tptapi.Service) *TptClientAdapter {
	return &TptClientAdapter{Svc: svc}
}

// client 拿当前登录 client;nil=未登录。
func (a *TptClientAdapter) client() *tptapi.TptClient {
	if a.Svc == nil {
		return nil
	}
	return a.Svc.Client()
}

func (a *TptClientAdapter) GetAllDsInfo() ([]tptapi.DsInfo, error) {
	c := a.client()
	if c == nil {
		return nil, &PublicError{Message: "未登录", Kind: "auth"}
	}
	return c.GetAllDsInfo()
}

func (a *TptClientAdapter) QueryTagsWithQuality(dsID *int, groupID, tagName, tagBaseName string,
	tagType, page, pageSize int, sort string) (json.RawMessage, error) {
	c := a.client()
	if c == nil {
		return nil, &PublicError{Message: "未登录", Kind: "auth"}
	}
	return c.QueryTagsWithQuality(dsID, groupID, tagName, tagBaseName, tagType, page, pageSize, sort)
}

func (a *TptClientAdapter) GetRTValue(tagNames []string) ([]tptapi.RtValuePoint, error) {
	c := a.client()
	if c == nil {
		return nil, &PublicError{Message: "未登录", Kind: "auth"}
	}
	return c.GetRTValue(tagNames)
}

func (a *TptClientAdapter) WriteTagValues(values map[string]any) error {
	c := a.client()
	if c == nil {
		return &PublicError{Message: "未登录", Kind: "auth"}
	}
	return c.WriteTagValues(values)
}

func (a *TptClientAdapter) GetHistoryValue(tagNames []string, begTime, endTime string,
	interval int, isSecond, isSource bool, offset, option int,
	page, pageSize int, sort string) (json.RawMessage, error) {
	c := a.client()
	if c == nil {
		return nil, &PublicError{Message: "未登录", Kind: "auth"}
	}
	return c.GetHistoryValue(tagNames, begTime, endTime, interval, isSecond, isSource, offset, option, page, pageSize, sort)
}

func (a *TptClientAdapter) GetHistoryValueFromDB(tagNames []string, begTime, endTime string,
	isSource, numberToString bool, page, pageSize int, sort string) (json.RawMessage, error) {
	c := a.client()
	if c == nil {
		return nil, &PublicError{Message: "未登录", Kind: "auth"}
	}
	return c.GetHistoryValueFromDB(tagNames, begTime, endTime, isSource, numberToString, page, pageSize, sort)
}

func (a *TptClientAdapter) ListGroupTagsRaw(groupID, tagName string, tagType, page, pageSize int) (json.RawMessage, error) {
	c := a.client()
	if c == nil {
		return nil, &PublicError{Message: "未登录", Kind: "auth"}
	}
	return c.ListGroupTags(groupID, tagName, tagType, page, pageSize, "-createTime")
}
