// Package excel 把 .xlsx 文件解析为 []api.UserDraft，并做基本校验。
//
// 设计要点：
//   - 仅支持 .xlsx（excelize 不支持旧版 .xls）
//   - 必须有表头行（第一行），列名固定为：username / password / nickName / email / phone
//   - 必填：username / password / nickName
//   - 校验失败不抛 panic，返回带 Row / Error 的 ParseResult，UI 可在预览表格中红字标错
//   - 解析完返回 *ParseResult，前端可二次编辑后再提交
package excel

import (
	"fmt"
	"strings"

	"github.com/xuri/excelize/v2"

	"user-manager/internal/api"
)

// ParseResult 是前端预览表格的数据源。
// Users 中的 Row 是 1-based 的 xlsx 行号（含表头，所以 Row=1 是表头，Row=2 是第一条数据）。
type ParseResult struct {
	Users    []ParsedRow `json:"users"`
	Errors   []ParseErr  `json:"errors"`
	Filename string      `json:"filename"`
}

// ParsedRow 单行解析结果。
type ParsedRow struct {
	Row    int           `json:"row"`    // 1-based xlsx row
	Draft  api.UserDraft `json:"draft"`  // 解析后的草稿
	Errors []string      `json:"errors"` // 该行的校验错误（行级）
}

// ParseErr 文件级 / 列级错误（不绑定特定行）。
type ParseErr struct {
	Row    int    `json:"row"`
	Column string `json:"column"`
	Msg    string `json:"msg"`
}

// Excel 列定义（写死，与 design.md §3.5 对齐）
var (
	colUsername = "username"
	colPassword = "password"
	colNickName = "nickName"
	colEmail    = "email"
	colPhone    = "phone"

	requiredCols = []string{colUsername, colPassword, colNickName}
	allCols      = []string{colUsername, colPassword, colNickName, colEmail, colPhone}
)

// ParseFile 解析 xlsx 文件。
//
// sheetName: 留空则取第一个 sheet
func ParseFile(filePath string, sheetName string) (*ParseResult, error) {
	f, err := excelize.OpenFile(filePath)
	if err != nil {
		return nil, fmt.Errorf("open xlsx: %w", err)
	}
	defer f.Close()

	if sheetName == "" {
		sheetName = f.GetSheetName(0)
		if sheetName == "" {
			return nil, fmt.Errorf("xlsx has no sheet")
		}
	}

	rows, err := f.GetRows(sheetName)
	if err != nil {
		return nil, fmt.Errorf("read sheet %q: %w", sheetName, err)
	}
	if len(rows) == 0 {
		return &ParseResult{Filename: filePath}, nil
	}

	// 第一行 = 表头。缺失列用 -1 哨兵，避免零值指向第一列。
	header := rows[0]
	colIdx := map[string]int{}
	for i, name := range header {
		colIdx[strings.TrimSpace(name)] = i
	}
	// 已知列若缺失，置 -1
	for _, c := range allCols {
		if _, ok := colIdx[c]; !ok {
			colIdx[c] = -1
		}
	}

	// 校验必填列存在
	var fileErrs []ParseErr
	for _, req := range requiredCols {
		if colIdx[req] < 0 {
			fileErrs = append(fileErrs, ParseErr{
				Row:    1,
				Column: req,
				Msg:    fmt.Sprintf("missing required column %q in header", req),
			})
		}
	}
	if len(fileErrs) > 0 {
		return &ParseResult{
			Filename: filePath,
			Errors:   fileErrs,
		}, nil
	}

	result := &ParseResult{
		Filename: filePath,
		Users:    []ParsedRow{}, // 初始化为空 slice，JSON 序列化为 [] 而不是 null（前端 .length 不炸）
		Errors:   []ParseErr{},
	}

	// 数据行（从 row=2 开始）
	for rowIdx := 1; rowIdx < len(rows); rowIdx++ {
		row := rows[rowIdx]
		xlsxRow := rowIdx + 1 // 1-based
		pr := ParsedRow{
			Row: xlsxRow,
			Draft: api.UserDraft{
				Username: cell(row, colIdx[colUsername]),
				Password: cell(row, colIdx[colPassword]),
				NickName: cell(row, colIdx[colNickName]),
				Email:    cell(row, colIdx[colEmail]),
				Phone:    cell(row, colIdx[colPhone]),
			},
			Errors: []string{}, // 同上，避免 JSON null
		}
		if errs := validate(&pr.Draft); len(errs) > 0 {
			pr.Errors = errs
			result.Errors = append(result.Errors, parseErrsFromRow(xlsxRow, errs)...)
		}
		result.Users = append(result.Users, pr)
	}
	return result, nil
}

// cell 安全读取单元格（防止越界 + 哨兵 -1）。
func cell(row []string, idx int) string {
	if idx < 0 || idx >= len(row) {
		return ""
	}
	return strings.TrimSpace(row[idx])
}

// validate 行级校验，返回错误列表。
func validate(d *api.UserDraft) []string {
	var errs []string
	if d.Username == "" {
		errs = append(errs, "username 不能为空")
	}
	if d.Password == "" {
		errs = append(errs, "password 不能为空")
	}
	if d.NickName == "" {
		errs = append(errs, "nickName 不能为空")
	}
	if d.Email != "" && !strings.Contains(d.Email, "@") {
		errs = append(errs, "email 格式不对")
	}
	if d.Phone != "" && len(d.Phone) < 6 {
		errs = append(errs, "phone 长度过短")
	}
	return errs
}

func parseErrsFromRow(row int, errs []string) []ParseErr {
	out := make([]ParseErr, len(errs))
	for i, e := range errs {
		out[i] = ParseErr{Row: row, Msg: e}
	}
	return out
}
