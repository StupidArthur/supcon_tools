package wecom

// messages.go: 企业微信消息体 payload 构建(纯逻辑, 无网络依赖, 可独立 go test)。
// 与 Python 版 notifier/wecom/messages.py 行为一致。

import (
	"crypto/md5"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"os"
)

// NewsArticleMax 企业微信限制单条 news 最多 8 篇。
const NewsArticleMax = 8

// NewsArticle 图文消息单篇。
type NewsArticle struct {
	Title       string `json:"title"`
	Description string `json:"description,omitempty"`
	URL         string `json:"url,omitempty"`
	PicURL      string `json:"picurl,omitempty"`
}

// BuildText 构建文本消息 payload。mentionAll 等价于 mentioned_list=["@all"]。
func BuildText(content string, mentionedList, mentionedMobileList []string, mentionAll bool) (map[string]any, error) {
	if content == "" {
		return nil, fmt.Errorf("wecom: content 不能为空")
	}
	text := map[string]any{"content": content}
	if mentionAll {
		text["mentioned_list"] = []string{"@all"}
	} else {
		if len(mentionedList) > 0 {
			text["mentioned_list"] = mentionedList
		}
		if len(mentionedMobileList) > 0 {
			text["mentioned_mobile_list"] = mentionedMobileList
		}
	}
	return map[string]any{"msgtype": "text", "text": text}, nil
}

// BuildMarkdown 构建 markdown 消息 payload。markdown 不支持 @提醒。
func BuildMarkdown(content string) (map[string]any, error) {
	if content == "" {
		return nil, fmt.Errorf("wecom: content 不能为空")
	}
	return map[string]any{"msgtype": "markdown", "markdown": map[string]any{"content": content}}, nil
}

// BuildImageFromBytes 从图片字节构建 image 消息 payload(自动算 base64+md5)。
func BuildImageFromBytes(data []byte) (map[string]any, error) {
	if len(data) == 0 {
		return nil, fmt.Errorf("wecom: data 不能为空")
	}
	sum := md5.Sum(data)
	return map[string]any{
		"msgtype": "image",
		"image": map[string]any{
			"base64": base64.StdEncoding.EncodeToString(data),
			"md5":    hex.EncodeToString(sum[:]),
		},
	}, nil
}

// BuildImageFromFile 从图片文件构建 image 消息 payload。
func BuildImageFromFile(path string) (map[string]any, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return BuildImageFromBytes(data)
}

// BuildNews 构建图文消息 payload, 1~8 篇。
func BuildNews(articles []NewsArticle) (map[string]any, error) {
	if len(articles) == 0 {
		return nil, fmt.Errorf("wecom: articles 不能为空")
	}
	if len(articles) > NewsArticleMax {
		return nil, fmt.Errorf("wecom: articles 最多 %d 篇, 当前 %d", NewsArticleMax, len(articles))
	}
	arts := make([]map[string]any, 0, len(articles))
	for _, a := range articles {
		if a.Title == "" {
			return nil, fmt.Errorf("wecom: 每篇 article 必须有 title")
		}
		m := map[string]any{"title": a.Title}
		if a.Description != "" {
			m["description"] = a.Description
		}
		if a.URL != "" {
			m["url"] = a.URL
		}
		if a.PicURL != "" {
			m["picurl"] = a.PicURL
		}
		arts = append(arts, m)
	}
	return map[string]any{"msgtype": "news", "news": map[string]any{"articles": arts}}, nil
}

// BuildFile 构建文件消息 payload, mediaID 由 UploadMedia 获得。
func BuildFile(mediaID string) (map[string]any, error) {
	if mediaID == "" {
		return nil, fmt.Errorf("wecom: media_id 不能为空")
	}
	return map[string]any{"msgtype": "file", "file": map[string]any{"media_id": mediaID}}, nil
}

// BuildTemplateCard 构建模板卡片消息 payload。card 结构随 card_type 变化,
// 这里只校验 card_type 存在, 其余字段交调用方按官方文档构造。
func BuildTemplateCard(card map[string]any) (map[string]any, error) {
	if card == nil {
		return nil, fmt.Errorf("wecom: card 不能为 nil")
	}
	ct, ok := card["card_type"].(string)
	if !ok || ct == "" {
		return nil, fmt.Errorf("wecom: card 必须包含 card_type")
	}
	return map[string]any{"msgtype": "template_card", "template_card": card}, nil
}
