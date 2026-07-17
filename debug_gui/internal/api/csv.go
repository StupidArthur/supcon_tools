package api

import (
	"encoding/csv"
	"fmt"
	"io"
	"os"
	"strconv"
)

// BatchResult 是批量仿真的返回结果
type BatchResult struct {
	Columns []string         `json:"columns"`
	Rows    []map[string]any `json:"rows"`
}

// ParseCSV 解析 CSV 文件为 BatchResult
func ParseCSV(path string) (BatchResult, error) {
	file, err := os.Open(path)
	if err != nil {
		return BatchResult{}, fmt.Errorf("读取 CSV 失败: %w", err)
	}
	defer file.Close()

	reader := csv.NewReader(file)
	headers, err := reader.Read()
	if err != nil {
		return BatchResult{}, fmt.Errorf("解析 CSV 表头失败: %w", err)
	}

	var rows []map[string]any
	rowIdx := 0
	for {
		record, err := reader.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			break
		}
		row := map[string]any{"_cycle": rowIdx}
		for i, value := range record {
			if i >= len(headers) {
				break
			}
			if f, err := strconv.ParseFloat(value, 64); err == nil {
				row[headers[i]] = f
			} else {
				row[headers[i]] = value
			}
		}
		rows = append(rows, row)
		rowIdx++
	}

	return BatchResult{
		Columns: append([]string{"_cycle"}, headers...),
		Rows:    rows,
	}, nil
}
