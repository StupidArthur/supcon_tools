package main

import (
	"bufio"
	"encoding/csv"
	"fmt"
	"io"
	"os"
	"strings"
	"sync"
	"unicode/utf8"

	"golang.org/x/text/encoding/htmlindex"
	"golang.org/x/text/encoding/simplifiedchinese"
	"golang.org/x/text/transform"
)

// CSVRecord 表示 CSV 发布配置中的一行。
type CSVRecord struct {
	Name        string `json:"name"`
	Release     string `json:"release"`     // "是" 或 "否"
	Cores       string `json:"cores"`       // 可空
	Replicas    string `json:"replicas"`    // 可空
	Position    string `json:"position"`    // CPU/GPU，可空
}

// PublishItem 待发布的算法项。
type PublishItem struct {
	ID           float64 `json:"id"`
	Name         string  `json:"name"`
	Cores        float64 `json:"cores"`
	NumReplicas  int     `json:"numReplicas"`
	ResourceType int     `json:"resourceType"` // 1=CPU, 2=GPU
}

// CompareResult CSV 与平台算法的比对结果。
type CompareResult struct {
	Differences      []string       `json:"differences"`       // 差异列表
	ToRelease        []PublishItem  `json:"toRelease"`         // 待发布
	AlreadyReleased  []string       `json:"alreadyReleased"`   // 已发布（跳过）
	ShouldNotRelease []string       `json:"shouldNotRelease"`  // CSV设否但平台已发布
	NotInPlatform    []string       `json:"notInPlatform"`     // CSV有但平台没有
	Error            string         `json:"error"`
}

// LoadCSV 加载 CSV 发布配置文件。
// 自动识别 UTF-8 BOM / UTF-8 / GBK / GB18030 四种常见中文编码。
func LoadCSV(path string) ([]CSVRecord, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	// 关键：所有读取都走同一个 bufio.Reader，否则 detectCSVEncoding 内部的
	// bufio.Peek(4096) 会把 os.File 读穿到 EOF，后面再读 f 就读不到数据。
	br := bufio.NewReader(f)

	// 1) 检查并跳过 UTF-8 BOM
	head, _ := br.Peek(3)
	hasBOM := len(head) >= 3 && head[0] == 0xEF && head[1] == 0xBB && head[2] == 0xBF
	if hasBOM {
		br.Discard(3)
	}

	// 2) 探测编码；识别为 UTF-8 时不包 transformer
	tr, detected := detectCSVEncoding(br)
	var raw io.Reader = br
	if tr != nil {
		raw = transform.NewReader(br, tr)
	}

	reader := csv.NewReader(raw)
	rows, err := reader.ReadAll()
	if err != nil {
		return nil, fmt.Errorf("CSV 解析失败（已尝试编码 %s）: %w", detected, err)
	}
	if len(rows) < 2 {
		return nil, fmt.Errorf("CSV 文件无数据行")
	}

	// 第一行是列头，建立列名到索引的映射
	header := rows[0]
	colIndex := make(map[string]int)
	for i, h := range header {
		colIndex[strings.TrimSpace(h)] = i
	}

	var records []CSVRecord
	for _, row := range rows[1:] {
		rec := CSVRecord{
			Name:     getCSVField(row, colIndex, "算法名称"),
			Release:  getCSVField(row, colIndex, "是否发布"),
			Cores:    getCSVField(row, colIndex, "核数"),
			Replicas: getCSVField(row, colIndex, "副本数"),
			Position: getCSVField(row, colIndex, "发布位置"),
		}
		if rec.Name != "" {
			records = append(records, rec)
		}
	}
	return records, nil
}

func getCSVField(row []string, colIndex map[string]int, colName string) string {
	idx, ok := colIndex[colName]
	if !ok || idx >= len(row) {
		return ""
	}
	return strings.TrimSpace(row[idx])
}

// CompareAlgorithms 将 CSV 配置与平台算法比对，产出差异和待发布列表。
func (a *AlgAPI) CompareAlgorithms(csvRecords []CSVRecord) *CompareResult {
	// 用 zhName 构建平台算法映射（大小写不敏感）
	platformMap := make(map[string]map[string]any)
	for _, algo := range a.algorithms {
		if zhName, _ := algo["zhName"].(string); zhName != "" {
			platformMap[strings.ToLower(zhName)] = algo
		}
	}

	result := &CompareResult{}

	for _, row := range csvRecords {
		if row.Name == "" {
			continue
		}
		lowerName := strings.ToLower(row.Name)

		platformAlgo, ok := platformMap[lowerName]
		if !ok {
			result.Differences = append(result.Differences,
				fmt.Sprintf("  - %s (CSV 中存在，平台中未找到)", row.Name))
			result.NotInPlatform = append(result.NotInPlatform, row.Name)
			continue
		}

		algoID, _ := platformAlgo["id"].(float64)
		isRelease, _ := platformAlgo["isRelease"].(float64)
		platformCores, _ := platformAlgo["cores"].(float64)
		platformReplicas, _ := platformAlgo["numReplicas"].(float64)
		platformResourceType, _ := platformAlgo["resourceType"].(float64)

		// 检查参数差异
		if row.Cores != "" {
			csvCores := parseFloat(row.Cores)
			if csvCores != platformCores {
				result.Differences = append(result.Differences,
					fmt.Sprintf("  - %s: 核数差异 (平台: %v, CSV: %s)", row.Name, platformCores, row.Cores))
			}
		}
		if row.Replicas != "" {
			csvReplicas := parseInt(row.Replicas)
			if csvReplicas != int(platformReplicas) {
				result.Differences = append(result.Differences,
					fmt.Sprintf("  - %s: 副本数差异 (平台: %v, CSV: %s)", row.Name, platformReplicas, row.Replicas))
			}
		}
		if row.Position != "" {
			csvMode := 1
			if row.Position == "GPU" {
				csvMode = 2
			}
			if csvMode != int(platformResourceType) {
				platformMode := "CPU"
				if platformResourceType == 2 {
					platformMode = "GPU"
				}
				result.Differences = append(result.Differences,
					fmt.Sprintf("  - %s: 发布位置差异 (平台: %s, CSV: %s)", row.Name, platformMode, row.Position))
			}
		}

		// 判断是否需要发布
		if row.Release != "是" {
			if isRelease == 1 {
				result.ShouldNotRelease = append(result.ShouldNotRelease, row.Name)
			}
			continue
		}

		if isRelease == 1 {
			result.AlreadyReleased = append(result.AlreadyReleased, row.Name)
		} else {
			// 组装待发布项，CSV 有值用 CSV，否则用平台已有值
			cores := platformCores
			if row.Cores != "" {
				cores = parseFloat(row.Cores)
			}
			replicas := int(platformReplicas)
			if row.Replicas != "" {
				replicas = parseInt(row.Replicas)
			}
			resourceType := 1
			if row.Position == "GPU" {
				resourceType = 2
			}
			result.ToRelease = append(result.ToRelease, PublishItem{
				ID:           algoID,
				Name:         row.Name,
				Cores:        cores,
				NumReplicas:  replicas,
				ResourceType: resourceType,
			})
		}
	}

	return result
}

// PublishAlgorithms 并发批量发布算法，通过 logFn 回调实时推送日志。
// 按 concurrent 数分批，批内多线程并行，批间顺序执行。
func (a *AlgAPI) PublishAlgorithms(items []PublishItem, concurrent int, logFn func(string)) {
	total := len(items)
	if concurrent <= 0 {
		concurrent = 1
	}

	for i := 0; i < total; i += concurrent {
		end := i + concurrent
		if end > total {
			end = total
		}
		batch := items[i:end]
		batchNum := i/concurrent + 1
		batchTotal := (total + concurrent - 1) / concurrent

		var names []string
		for _, x := range batch {
			names = append(names, x.Name)
		}
		logFn(fmt.Sprintf("\n[批次 %d/%d] 正在发布: %v", batchNum, batchTotal, names))

		var wg sync.WaitGroup
		for _, item := range batch {
			wg.Add(1)
			go func(item PublishItem) {
				defer wg.Done()
				err := a.ReleaseAlgorithm(item.ID, 1, int(item.Cores), item.ResourceType, item.NumReplicas)
				if err != nil {
					logFn(fmt.Sprintf("  ✗ %s 发布失败: %v", item.Name, err))
				} else {
					logFn(fmt.Sprintf("  ✓ %s 发布成功", item.Name))
				}
			}(item)
		}
		wg.Wait()

		logFn(fmt.Sprintf("[批次 %d/%d] 完成", batchNum, batchTotal))
	}
}

// VerifyPublished 发布后重新拉取算法列表，校验发布结果。
// 返回未成功发布的算法名称列表。
func (a *AlgAPI) VerifyPublished(items []PublishItem, logFn func(string)) []string {
	logFn("[校验] 重新获取平台算法列表...")
	if _, err := a.GetAllAlgorithms(); err != nil {
		logFn(fmt.Sprintf("[校验] 获取算法列表失败: %v", err))
		return nil
	}

	var stillPending []string
	for _, item := range items {
		algo := a.GetByID(item.ID)
		if algo != nil {
			if isRelease, _ := algo["isRelease"].(float64); isRelease == 1 {
				logFn(fmt.Sprintf("  ✓ %s 已发布成功", item.Name))
				continue
			}
		}
		logFn(fmt.Sprintf("  ✗ %s 发布失败或状态异常", item.Name))
		stillPending = append(stillPending, item.Name)
	}
	return stillPending
}

func parseFloat(s string) float64 {
	var f float64
	fmt.Sscanf(s, "%f", &f)
	return f
}

func parseInt(s string) int {
	var i int
	fmt.Sscanf(s, "%d", &i)
	return i
}

// detectCSVEncoding 探测 CSV 文件编码，返回对应的 transformer 和识别结果名。
// 策略：先看 BOM，没有 BOM 就把开头一段作为 UTF-8 验证，失败则按 GBK/GB18030 处理。
// 返回的 transformer 可直接传给 transform.NewReader；识别为 UTF-8 时返回 nil 表示不需要解码。
func detectCSVEncoding(r io.Reader) (transform.Transformer, string) {
	br := bufio.NewReader(r)
	head, err := br.Peek(4096)
	if err != nil && err != io.EOF {
		return nil, "utf-8"
	}

	// 1) BOM 优先：UTF-8 BOM / UTF-16 LE/BE
	if len(head) >= 3 && head[0] == 0xEF && head[1] == 0xBB && head[2] == 0xBF {
		// BOM 已经在调用方剥掉了，这里不会走到
		return nil, "utf-8"
	}
	if len(head) >= 2 && head[0] == 0xFF && head[1] == 0xFE {
		if enc, _ := htmlindex.Get("utf-16le"); enc != nil {
			return enc.NewDecoder(), "utf-16le"
		}
	}
	if len(head) >= 2 && head[0] == 0xFE && head[1] == 0xFF {
		if enc, _ := htmlindex.Get("utf-16be"); enc != nil {
			return enc.NewDecoder(), "utf-16be"
		}
	}

	// 2) 无 BOM：尝试 UTF-8 严格校验
	if utf8.Valid(head) {
		return nil, "utf-8"
	}

	// 3) 兜底：当作 GBK/GB18030（GB18030 是 GBK 超集，覆盖全部中日韩字符）
	if enc, _ := htmlindex.Get("gb18030"); enc != nil {
		return enc.NewDecoder(), "gb18030 (含 GBK)"
	}
	return simplifiedchinese.GBK.NewDecoder(), "gbk"
}
