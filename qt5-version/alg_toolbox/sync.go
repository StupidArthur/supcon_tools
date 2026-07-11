package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ScanResult 扫描本地文件并匹配平台算法的结果。
type ScanResult struct {
	Found     []map[string]any `json:"found"`     // 命中平台的算法列表
	Published []map[string]any `json:"published"`  // 其中已发布的算法
	Error     string           `json:"error"`
}

// ScanLocalFiles 扫描本地算法目录并匹配平台算法。
func (a *AlgAPI) ScanLocalFiles(dir string) *ScanResult {
	matched, err := a.MatchLocalFiles(dir)
	if err != nil {
		return &ScanResult{Error: err.Error()}
	}

	var found, published []map[string]any
	for _, item := range matched {
		if isExist, _ := item["isExist"].(bool); isExist {
			found = append(found, item)
			if isRelease, _ := item["isRelease"].(float64); isRelease == 1 {
				published = append(published, item)
			}
		}
	}
	return &ScanResult{Found: found, Published: published}
}

// SyncOptions 同步流程的选项。
type SyncOptions struct {
	Dir      string // 本地算法目录
	SkipEdit bool   // 是否跳过编辑步骤（对应 alg_sync_no_edit）
}

// SyncAlgorithms 执行同步流程，通过 logFn 回调实时推送日志。
// 流程：已发布算法取消发布 → 上传文件 → (可选)编辑 → 重新发布；未发布算法上传 → (可选)编辑
func (a *AlgAPI) SyncAlgorithms(opts SyncOptions, logFn func(string)) error {
	result := a.ScanLocalFiles(opts.Dir)
	if result.Error != "" {
		return fmt.Errorf("%s", result.Error)
	}

	found := result.Found
	published := result.Published

	// 用 map 标记已发布的算法 ID，便于后续判断
	publishedIDs := make(map[float64]bool)
	for _, item := range published {
		if id, ok := item["id"].(float64); ok {
			publishedIDs[id] = true
		}
	}

	logFn(fmt.Sprintf("[同步开始] 共 %d 个算法待处理", len(found)))

	for idx, item := range found {
		name, _ := item["name"].(string)
		algoID, _ := item["id"].(float64)
		zhName, _ := item["zhName"].(string)
		isPublished := publishedIDs[algoID]
		filePath := filepath.Join(opts.Dir, name)

		logFn(fmt.Sprintf("[%d/%d] 处理: %s  id=%v  zhName=%s", idx+1, len(found), name, int(algoID), zhName))

		// 已发布算法：先取消发布
		if isPublished {
			logFn("    取消发布...")
			cores := toInt(item["cores"])
			resourceType := toInt(item["resourceType"])
			numReplicas := toInt(item["numReplicas"])
			if err := a.ReleaseAlgorithm(algoID, 0, cores, resourceType, numReplicas); err != nil {
				return err
			}
			logFn("    [取消发布 OK]")
		}

		// 上传文件
		logFn(fmt.Sprintf("    上传文件: %s...", filePath))
		uploadRes, err := a.UploadFile(filePath)
		if err != nil {
			return err
		}
		msg, _ := uploadRes["message"].(string)
		logFn(fmt.Sprintf("    [上传 OK] %s", msg))

		// 编辑算法（可选）
		if !opts.SkipEdit {
			logFn("    编辑算法...")
			editRes, err := a.EditAlgorithm(name)
			if err != nil {
				return err
			}
			editID, _ := editRes["id"].(float64)
			editZhName, _ := editRes["zhName"].(string)
			editIsRelease, _ := editRes["isRelease"].(float64)
			logFn(fmt.Sprintf("    [编辑 OK] id=%v, zhName=%s, isRelease=%v", int(editID), editZhName, int(editIsRelease)))
		}

		// 已发布算法：重新发布
		if isPublished {
			logFn("    重新发布...")
			cores := toInt(item["cores"])
			resourceType := toInt(item["resourceType"])
			numReplicas := toInt(item["numReplicas"])
			if err := a.ReleaseAlgorithm(algoID, 1, cores, resourceType, numReplicas); err != nil {
				return err
			}
			logFn("    [重新发布 OK]")
		}

		logFn("    完成")
	}

	logFn("============================================================")
	logFn("任务完成")
	logFn(fmt.Sprintf("  命中平台: %d 个", len(found)))
	logFn(fmt.Sprintf("  已发布待处理: %d 个", len(published)))
	return nil
}

// ExportAlgorithms 将缓存的算法信息导出为 CSV 文件。
func (a *AlgAPI) ExportAlgorithms(savePath string) error {
	if len(a.algorithms) == 0 {
		return fmt.Errorf("无算法数据，请先连接平台获取算法列表")
	}

	// 动态收集所有算法记录的 key 作为 CSV 列头
	var allKeys []string
	seen := make(map[string]bool)
	for _, algo := range a.algorithms {
		for k := range algo {
			if !seen[k] {
				allKeys = append(allKeys, k)
				seen[k] = true
			}
		}
	}

	f, err := os.Create(savePath)
	if err != nil {
		return err
	}
	defer f.Close()

	// BOM 头保证 Excel 正确识别 UTF-8
	f.Write([]byte{0xEF, 0xBB, 0xBF})

	// 写列头
	for i, k := range allKeys {
		if i > 0 {
			f.Write([]byte(","))
		}
		f.Write([]byte(escapeCSV(k)))
	}
	f.Write([]byte("\n"))

	// 写数据行
	for _, algo := range a.algorithms {
		for i, k := range allKeys {
			if i > 0 {
				f.Write([]byte(","))
			}
			f.Write([]byte(escapeCSV(fmt.Sprintf("%v", algo[k]))))
		}
		f.Write([]byte("\n"))
	}

	return nil
}

// escapeCSV 简单的 CSV 字段转义：含逗号或引号时用双引号包裹。
func escapeCSV(s string) string {
	if !strings.Contains(s, ",") && !strings.Contains(s, "\"") && !strings.Contains(s, "\n") {
		return s
	}
	return `"` + strings.ReplaceAll(s, `"`, `""`) + `"`
}

// toInt 将 any 安全转为 int（平台返回的数字可能是 float64）。
func toInt(v any) int {
	switch n := v.(type) {
	case float64:
		return int(n)
	case int:
		return n
	default:
		return 1
	}
}
