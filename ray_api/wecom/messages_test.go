package wecom

// messages_test.go: Build_* 纯逻辑单测, 覆盖 happy / 空 / 非法 / 边界四类场景。
// 不依赖网络, go test 即可运行。

import "testing"

func TestBuildText(t *testing.T) {
	// happy
	p, err := BuildText("hi", nil, nil, false)
	if err != nil {
		t.Fatalf("happy: %v", err)
	}
	if p["msgtype"] != "text" {
		t.Fatalf("msgtype = %v", p["msgtype"])
	}
	// mentionAll
	p, _ = BuildText("hi", nil, nil, true)
	text := p["text"].(map[string]any)
	ml := text["mentioned_list"].([]string)
	if len(ml) != 1 || ml[0] != "@all" {
		t.Fatalf("mentionAll = %v", ml)
	}
	// 空内容(非法)
	if _, err := BuildText("", nil, nil, false); err == nil {
		t.Fatal("want error for empty content")
	}
	// mentioned_list 透传
	p, _ = BuildText("hi", []string{"u1", "u2"}, nil, false)
	text = p["text"].(map[string]any)
	if len(text["mentioned_list"].([]string)) != 2 {
		t.Fatal("mentioned_list not passed")
	}
}

func TestBuildMarkdown(t *testing.T) {
	p, err := BuildMarkdown("# title")
	if err != nil {
		t.Fatalf("happy: %v", err)
	}
	if p["msgtype"] != "markdown" {
		t.Fatalf("msgtype = %v", p["msgtype"])
	}
	if _, err := BuildMarkdown(""); err == nil {
		t.Fatal("want error for empty content")
	}
}

func TestBuildImageFromBytes(t *testing.T) {
	// happy
	p, err := BuildImageFromBytes([]byte{1, 2, 3})
	if err != nil {
		t.Fatalf("happy: %v", err)
	}
	img := p["image"].(map[string]any)
	if img["base64"] == "" || img["md5"] == "" {
		t.Fatal("base64/md5 missing")
	}
	// 空(非法)
	if _, err := BuildImageFromBytes(nil); err == nil {
		t.Fatal("want error for empty data")
	}
}

func TestBuildNews(t *testing.T) {
	// happy
	p, err := BuildNews([]NewsArticle{{Title: "a"}})
	if err != nil {
		t.Fatalf("happy: %v", err)
	}
	if p["msgtype"] != "news" {
		t.Fatalf("msgtype = %v", p["msgtype"])
	}
	// 空(非法)
	if _, err := BuildNews(nil); err == nil {
		t.Fatal("want error for empty articles")
	}
	// 边界: 超过上限
	arts := make([]NewsArticle, NewsArticleMax+1)
	for i := range arts {
		arts[i] = NewsArticle{Title: "x"}
	}
	if _, err := BuildNews(arts); err == nil {
		t.Fatal("want error for too many articles")
	}
	// 边界: 正好上限
	arts = arts[:NewsArticleMax]
	if _, err := BuildNews(arts); err != nil {
		t.Fatalf("max boundary: %v", err)
	}
	// 非法: 缺 title
	if _, err := BuildNews([]NewsArticle{{}}); err == nil {
		t.Fatal("want error for missing title")
	}
}

func TestBuildFile(t *testing.T) {
	p, err := BuildFile("mid123")
	if err != nil {
		t.Fatalf("happy: %v", err)
	}
	if p["msgtype"] != "file" {
		t.Fatalf("msgtype = %v", p["msgtype"])
	}
	if _, err := BuildFile(""); err == nil {
		t.Fatal("want error for empty media_id")
	}
}

func TestBuildTemplateCard(t *testing.T) {
	// happy
	p, err := BuildTemplateCard(map[string]any{"card_type": "text_notice"})
	if err != nil {
		t.Fatalf("happy: %v", err)
	}
	if p["msgtype"] != "template_card" {
		t.Fatalf("msgtype = %v", p["msgtype"])
	}
	// 非法: 缺 card_type
	if _, err := BuildTemplateCard(map[string]any{}); err == nil {
		t.Fatal("want error for missing card_type")
	}
	// 非法: nil
	if _, err := BuildTemplateCard(nil); err == nil {
		t.Fatal("want error for nil card")
	}
}
