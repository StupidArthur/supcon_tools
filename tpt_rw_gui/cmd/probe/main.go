// tpt_rw_gui 探针工具 v3。
//
// 用法:
//   go run ./cmd/probe               # 默认走 env.json,7 步全流程
//   go run ./cmd/probe --ds 36 --tag 1_LIC8398.PV        # 探指定 DS + tagName
//   go run ./cmd/probe --ds 36 --mode list                # 只列 zzfmock 下的位号
//   go run ./cmd/probe --mode rt --tag xxx                # 只跑 RT 探测
//
// flag 说明:
//   --ds <int>       数据源 ID(由 ListDataSources 给出)。不指定时,自动选列表里第一个 alive=true 的。
//   --tag <string>   位号名。不指定时:若 --mode=list 列出 ds 下所有位号;否则取 ds 下第一个 tag。
//   --mode <string>  auto|list|rt|write|history|all
//                    auto = 上面 7 步(同 v2)
//                    list = 只列 ds 下位号(可缺 --tag)
//                    rt = 只读 RT
//                    write = 写值
//                    history = 读历史
//                    all = 强制跑全部
//   --url <string>   覆盖 env.json 的 baseUrl
//   --user <string>  覆盖 env.json 的 username
//   --pass <string>  覆盖 env.json 的 password
//   --tenant <string> 覆盖 env.json 的 tenantId
//
// 输出:每步打响应 raw bytes;超长截断。始终把 password 屏蔽为 ***。
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/yzc/tpt_api"
)

type ProbeConfig struct {
	BaseURL  string `json:"baseUrl"`
	Username string `json:"username"`
	Password string `json:"password"`
	TenantID string `json:"tenantId"`
}

type Flags struct {
	DS     int
	Tag    string
	Mode   string
	URL    string
	User   string
	Pass   string
	Tenant string
}

func main() {
	f := parseFlags()
	cfg, err := loadConfig("../env.json")
	if err != nil {
		fmt.Printf("读 env.json 失败: %v\n", err)
		os.Exit(1)
	}
	if f.URL != "" {
		cfg.BaseURL = strings.TrimRight(f.URL, "/")
	} else {
		cfg.BaseURL = strings.TrimRight(cfg.BaseURL, "/")
	}
	if f.User != "" {
		cfg.Username = f.User
	}
	if f.Pass != "" {
		cfg.Password = f.Pass
	}
	if f.Tenant != "" {
		cfg.TenantID = f.Tenant
	}

	fmt.Println("===== 探针 v3 =====")
	fmt.Printf("BaseURL=%s\nUsername=%s\nPassword=***(%d chars)\nTenantID=%q\n",
		cfg.BaseURL, cfg.Username, len(cfg.Password), cfg.TenantID)
	if f.DS > 0 {
		fmt.Printf("--ds=%d\n", f.DS)
	}
	if f.Tag != "" {
		fmt.Printf("--tag=%q\n", f.Tag)
	}
	fmt.Printf("--mode=%s\n\n", f.Mode)

	// 1. Login
	svc := tptapi.NewService()
	loginStart := time.Now()
	if _, err := svc.Login(cfg.BaseURL, cfg.Username, cfg.Password, cfg.TenantID, 30*time.Second); err != nil {
		fmt.Printf("[Login] 失败(%v): %v\n\n", time.Since(loginStart), err)
		os.Exit(2)
	}
	cli := svc.Client()
	fmt.Printf("[Login] OK(%v)\n\n", time.Since(loginStart))

	// 2. ListDataSources
	dsList, err := cli.GetAllDsInfo()
	if err != nil {
		fmt.Printf("[ListDataSources] 失败: %v\n\n", err)
		os.Exit(3)
	}
	fmt.Printf("[ListDataSources] OK(%d 条):\n", len(dsList))
	sort.Slice(dsList, func(i, j int) bool { return dsList[i].ID < dsList[j].ID })
	for _, d := range dsList {
		marker := "  "
		if int(d.ID) == f.DS {
			marker = "* " // 用户指定的 DS,标星
		}
		fmt.Printf("  %s id=%-4d name=%-30s sub=%d alive=%v url=%s\n",
			marker, d.ID, d.DsName, d.DsSubType, d.Alive, d.DsTarUrl)
	}
	fmt.Println()

	// 选 DS
	pickedDS := selectDS(dsList, f.DS)
	if pickedDS == nil {
		fmt.Printf("找不到 dsID=%d 的数据源,停止\n", f.DS)
		os.Exit(4)
	}
	fmt.Printf("PickedDS = id=%d name=%q (alive=%v)\n\n", pickedDS.ID, pickedDS.Name, pickedDS.Alive)

	// 模式分支
	switch f.Mode {
	case "list":
		runListTags(cli, pickedDS.ID, f.Tag)
	case "rt":
		runRT(cli, pickedDS.ID, f.Tag)
	case "write":
		runWrite(cli, pickedDS.ID, f.Tag)
	case "history":
		runHistory(cli, pickedDS.ID, f.Tag)
	case "all":
		runFull(cli, dsList, pickedDS.ID, f.Tag)
	case "auto":
		// 默认行为同 v2:自动选 alive 的第一个 DS,跑 7 步全流程
		fallthrough
	default:
		if f.DS == 0 {
			// 没有 --ds 且 mode=auto:按"listTags 全扫"自动找第一条
			runFull(cli, dsList, pickedDS.ID, f.Tag)
		} else {
			runFull(cli, dsList, pickedDS.ID, f.Tag)
		}
	}
	fmt.Println()
	fmt.Println("===== 探针结束 =====")
	_ = os.Stdout.Sync()
}

var (
	flagDS     int
	flagTag    string
	flagMode   string
	flagURL    string
	flagUser   string
	flagPass   string
	flagTenant string
)

func parseFlags() Flags {
	fs := flag.NewFlagSet("probe", flag.ExitOnError)
	fs.IntVar(&flagDS, "ds", 0, "数据源 ID(0=自动选)")
	fs.StringVar(&flagTag, "tag", "", "位号名(空=按 ds 自动)")
	fs.StringVar(&flagMode, "mode", "auto", "auto|list|rt|write|history|all")
	fs.StringVar(&flagURL, "url", "", "覆盖 env.json.baseUrl")
	fs.StringVar(&flagUser, "user", "", "覆盖 env.json.username")
	fs.StringVar(&flagPass, "pass", "", "覆盖 env.json.password")
	fs.StringVar(&flagTenant, "tenant", "", "覆盖 env.json.tenantId")
	_ = fs.Parse(os.Args[1:])
	mode := flagMode
	if mode == "" {
		mode = "auto"
	}
	return Flags{
		DS:     flagDS,
		Tag:    flagTag,
		Mode:   mode,
		URL:    flagURL,
		User:   flagUser,
		Pass:   flagPass,
		Tenant: flagTenant,
	}
}

// selectDS 选数据源:--ds 指定则精确匹配(找不到返 nil);否则取 alive=true 的第一条;再不行取首条。
func selectDS(list []tptapi.DsInfo, wantID int) *tptapi.DsInfo {
	if wantID > 0 {
		for i := range list {
			if int(list[i].ID) == wantID {
				return &list[i]
			}
		}
		return nil
	}
	for i := range list {
		if list[i].Alive {
			return &list[i]
		}
	}
	if len(list) > 0 {
		return &list[0]
	}
	return nil
}

// listTagsInDS 列 dsID 下所有位号(qtq) — 用来在 list 模式查 1_LIC8398.PV 是否真在。
func listTagsInDS(cli *tptapi.TptClient, dsID int) []tptapi.TagRecord {
	// 方法 1:用 GetTagsByDsID 走 /tag-info/page
	tags, err := cli.GetTagsByDsID(dsID)
	if err != nil {
		fmt.Printf("[ListTags-GetTagsByDsID] 错误: %v\n", err)
		return nil
	}
	return tags
}

// runListTags 模式:
//   - 列出该 DS 下所有位号(GetTagsByDsID 走 /tag-info/page?dsId=…)
//   - 若 --tag 指定,再额外查一次 GetTagByName 找精确名(跨 DS)
func runListTags(cli *tptapi.TptClient, dsID int, tagName string) {
	tags := listTagsInDS(cli, dsID)
	fmt.Printf("[ListTags] dsID=%d 下共 %d 条:\n", dsID, len(tags))
	hit := false
	for _, t := range tags {
		fmt.Printf("  id=%-6d tagName=%-40s base=%-30s dt=%d\n",
			t.ID, t.TagName, t.TagBaseName, t.DataType)
		if tagName != "" && t.TagName == tagName {
			hit = true
		}
	}
	if tagName != "" {
		if hit {
			fmt.Printf("\n[FindTag] %q 在 dsID=%d 下找到。\n", tagName, dsID)
		} else {
			fmt.Printf("\n[FindTag] %q 不在 dsID=%d 下(用 GetTagByName 跨 DS 查一次确认)。\n", tagName, dsID)
			fmt.Println("[GetTagByName]", tagName)
			raw, err := cli.GetTagByName(tagName)
			if err != nil {
				fmt.Printf("  错误: %v\n", err)
			} else {
				fmt.Printf("  OK,响应:%s\n", string(raw))
			}
		}
	}
}

// runRT 模式:读 RT
func runRT(cli *tptapi.TptClient, dsID int, tagName string) {
	if tagName == "" {
		fmt.Println("rt 模式需要 --tag 指定")
		return
	}
	fmt.Printf("[ReadRealtime] tagNames=%v (dsID=%d)\n", []string{tagName}, dsID)
	start := time.Now()
	pts, err := cli.GetRTValue([]string{tagName})
	fmt.Printf("  耗时 %v\n", time.Since(start))
	if err != nil {
		fmt.Printf("  错误: %T %v\n", err, err)
		return
	}
	for _, p := range pts {
		fmt.Printf("  tag=%s value=%v ts=%s app=%s q=%d dt=%d ok=%v msg=%q\n",
			p.TagName, string(p.TagValue), p.TagTime, p.AppTime, p.Quality, p.DataType, p.IsSuccess, p.Message)
	}
}

// runWrite 模式:写值 → 等 1s → 再读 RT
func runWrite(cli *tptapi.TptClient, _ int, tagName string) {
	if tagName == "" {
		fmt.Println("write 模式需要 --tag 指定")
		return
	}
	fmt.Printf("[WriteTagValues] tag=%s value=42.5\n", tagName)
	if err := cli.WriteTagValues(map[string]any{tagName: 42.5}); err != nil {
		fmt.Printf("  失败: %v\n", err)
		return
	}
	fmt.Println("  OK,等 1.2s 后回读…")
	time.Sleep(1200 * time.Millisecond)
	runRT(cli, 0, tagName)
}

// runHistory 模式:读历史 1min
func runHistory(cli *tptapi.TptClient, _ int, tagName string) {
	if tagName == "" {
		fmt.Println("history 模式需要 --tag 指定")
		return
	}
	end := time.Now()
	start := end.Add(-1 * time.Minute)
	fmt.Printf("[GetHistoryValueFromDB] tag=%s beg=%s end=%s\n",
		tagName, start.Format("2006-01-02 15:04:05"), end.Format("2006-01-02 15:04:05"))
	raw, err := cli.GetHistoryValueFromDB(
		[]string{tagName},
		start.Format("2006-01-02 15:04:05"),
		end.Format("2006-01-02 15:04:05"),
		false, false, 1, 100, "-appTime",
	)
	if err != nil {
		fmt.Printf("  错误: %v\n", err)
		return
	}
	fmt.Printf("  OK,响应(%d bytes):%s\n", len(raw), truncateForShow(string(raw), 1500))
}

// runFull 模式 (auto/all):v2 的 7 步全流程,只是 dsID / tagName 改成 --ds / --tag 驱动,fallback 用 pickedDS/pickedTag。
func runFull(cli *tptapi.TptClient, _ []tptapi.DsInfo, dsID int, tagName string) {
	if tagName == "" {
		// 先扫一下 dsID 下的所有位号,挑第一条
		tags := listTagsInDS(cli, dsID)
		if len(tags) > 0 {
			tagName = tags[0].TagName
			fmt.Printf("[AutoPickTag] 取 dsID=%d 下的第一条: %q\n", dsID, tagName)
		} else {
			tagName = "demo.t_double"
			fmt.Printf("[AutoPickTag] dsID=%d 下没有位号,硬编码 demo.t_double\n", dsID)
		}
	}
	fmt.Printf("\n[ReadRealtime] tagNames=%v\n", []string{tagName})
	pts, err := cli.GetRTValue([]string{tagName})
	if err != nil {
		fmt.Printf("  错误: %T %v\n", err, err)
	} else if len(pts) == 0 {
		fmt.Println("  OK,响应(0 条 — 位号可能存在但没数据,或位号本身不存在)")
	} else {
		for _, p := range pts {
			fmt.Printf("  tag=%s value=%s ts=%s app=%s q=%d\n",
				p.TagName, string(p.TagValue), p.TagTime, p.AppTime, p.Quality)
		}
	}

	// AddTag 试一下
	newTagName := fmt.Sprintf("probe_diag_%d", time.Now().Unix())
	created := false
	fmt.Printf("\n[AddTag] 注册 %q\n", newTagName)
	addErr := cli.AddTag(tptapi.AddTagParams{
		TagName: newTagName, TagBaseName: newTagName,
		DataType: 11, GroupID: tptapi.GroupRoot,
		Frequency: 10, OnlyRead: false,
	})
	if addErr != nil {
		fmt.Printf("  失败: %T %v\n\n", addErr, addErr)
	} else {
		fmt.Println("  OK")
		created = true
	}

	// 清理:函数退出时删掉创建的位号
	defer func() {
		if !created {
			return
		}
		fmt.Printf("\n[Cleanup] 删除 %q\n", newTagName)
		if _, err := cli.DeleteTagsByName([]string{newTagName}); err != nil {
			fmt.Printf("  清理失败: %v\n", err)
		} else {
			fmt.Println("  OK(已软删到回收站)")
		}
	}()

	// WriteTagValues
	fmt.Printf("\n[WriteTagValues] 写 %q = 42.5\n", newTagName)
	if err := cli.WriteTagValues(map[string]any{newTagName: 42.5}); err != nil {
		fmt.Printf("  失败: %v\n\n", err)
	} else {
		fmt.Println("  OK")
	}

	// ReadRealtime again
	fmt.Printf("\n[ReadRealtime-新位号] tagNames=%v\n", []string{newTagName})
	start := time.Now()
	pts2, err2 := cli.GetRTValue([]string{newTagName})
	fmt.Printf("  耗时 %v\n", time.Since(start))
	if err2 != nil {
		fmt.Printf("  错误: %T %v\n", err2, err2)
	} else if len(pts2) == 0 {
		fmt.Println("  OK,响应(0 条)")
	} else {
		for _, p := range pts2 {
			fmt.Printf("  tag=%s value=%s ts=%s app=%s q=%d\n",
				p.TagName, string(p.TagValue), p.TagTime, p.AppTime, p.Quality)
		}
	}

	// History
	runHistory(cli, dsID, newTagName)
}

func loadConfig(path string) (*ProbeConfig, error) {
	abs, _ := filepath.Abs(path)
	b, err := os.ReadFile(abs)
	if err != nil {
		return nil, fmt.Errorf("读 %s 失败: %w", abs, err)
	}
	var c ProbeConfig
	if err := json.Unmarshal(b, &c); err != nil {
		return nil, fmt.Errorf("parse %s 失败: %w", abs, err)
	}
	if c.BaseURL == "" || c.Username == "" || c.Password == "" {
		return nil, fmt.Errorf("env.json 缺字段")
	}
	return &c, nil
}

func truncateForShow(s string, max int) string {
	if len(s) <= max {
		return s
	}
	return s[:max] + fmt.Sprintf("...[truncated, total %d bytes]", len(s))
}
