package excel

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xuri/excelize/v2"
)

// makeTestXlsx 在 t.TempDir() 写一个 xlsx 文件，返回路径。
//
// rows[0] = header，其余 = 数据
func makeTestXlsx(t *testing.T, header []string, rows [][]string) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "test.xlsx")

	f := excelize.NewFile()
	defer f.Close()
	sheet := f.GetSheetName(0)

	if err := f.SetSheetRow(sheet, "A1", &header); err != nil {
		t.Fatalf("set header: %v", err)
	}
	for i, row := range rows {
		cell := fmt.Sprintf("A%d", i+2)
		if err := f.SetSheetRow(sheet, cell, &row); err != nil {
			t.Fatalf("set row %d: %v", i+2, err)
		}
	}
	if err := f.SaveAs(path); err != nil {
		t.Fatalf("save: %v", err)
	}
	return path
}

func TestParseFile_Valid(t *testing.T) {
	header := []string{"username", "password", "nickName", "email", "phone"}
	rows := [][]string{
		{"zhangsan", "Pwd@123", "张三", "z@x.com", "13800138000"},
		{"lisi", "Pwd@456", "李四", "", ""},
	}
	path := makeTestXlsx(t, header, rows)

	res, err := ParseFile(path, "")
	if err != nil {
		t.Fatalf("ParseFile: %v", err)
	}
	if len(res.Users) != 2 {
		t.Errorf("users = %d, want 2", len(res.Users))
	}
	if len(res.Errors) != 0 {
		t.Errorf("errors = %v, want none", res.Errors)
	}
	if res.Users[0].Draft.Username != "zhangsan" {
		t.Errorf("users[0].username = %q", res.Users[0].Draft.Username)
	}
	if res.Users[0].Row != 2 {
		t.Errorf("users[0].row = %d, want 2", res.Users[0].Row)
	}
	if res.Users[1].Draft.Email != "" {
		t.Errorf("users[1].email = %q, want empty", res.Users[1].Draft.Email)
	}
}

func TestParseFile_MissingRequiredColumn(t *testing.T) {
	header := []string{"username", "nickName"} // 缺 password
	rows := [][]string{{"a", "b"}}
	path := makeTestXlsx(t, header, rows)

	res, _ := ParseFile(path, "")
	if len(res.Errors) == 0 {
		t.Errorf("expected file-level error for missing column, got none")
	}
	found := false
	for _, e := range res.Errors {
		if e.Column == "password" {
			found = true
		}
	}
	if !found {
		t.Errorf("expected error mentioning column 'password', got %+v", res.Errors)
	}
}

func TestParseFile_RowValidation(t *testing.T) {
	header := []string{"username", "password", "nickName", "email"}
	rows := [][]string{
		{"ok1", "Pwd@1", "OK", "ok@x.com"},
		{"", "Pwd@2", "NoUser", "ok@x.com"},    // 缺 username
		{"ok3", "", "NoPwd", "ok@x.com"},       // 缺 password
		{"ok4", "Pwd@4", "BadEmail", "no-at"},  // email 格式错
		{"ok5", "Pwd@5", "ShortPhone", ""},     // phone 为空合法
	}
	path := makeTestXlsx(t, header, rows)

	res, err := ParseFile(path, "")
	if err != nil {
		t.Fatalf("ParseFile: %v", err)
	}
	if len(res.Users) != 5 {
		t.Errorf("users = %d, want 5", len(res.Users))
	}
	// 期望第 2/3/4 行有错
	if len(res.Users[0].Errors) != 0 {
		t.Errorf("users[0] errors = %v, want none", res.Users[0].Errors)
	}
	if len(res.Users[1].Errors) == 0 {
		t.Errorf("users[1] (missing username) should have errors")
	}
	if len(res.Users[2].Errors) == 0 {
		t.Errorf("users[2] (missing password) should have errors")
	}
	if len(res.Users[3].Errors) == 0 {
		t.Errorf("users[3] (bad email) should have errors")
	}
	if len(res.Users[4].Errors) != 0 {
		t.Errorf("users[4] errors = %v, want none", res.Users[4].Errors)
	}
}

func TestParseFile_EmptySheet(t *testing.T) {
	path := makeTestXlsx(t, []string{"username"}, nil)
	res, err := ParseFile(path, "")
	if err != nil {
		t.Fatalf("ParseFile: %v", err)
	}
	if len(res.Users) != 0 {
		t.Errorf("users = %d, want 0", len(res.Users))
	}
}

// TestParseFile_NoNullSlices 回归测试：确保空 slice 序列化为 [] 而非 null。
// null 会让前端 .length throw → 白屏。
func TestParseFile_NoNullSlices(t *testing.T) {
	header := []string{"username", "password", "nickName", "email", "phone"}
	rows := [][]string{
		{"ok1", "Pwd@1", "OK", "ok@x.com", "13800138000"}, // 全部合法
	}
	path := makeTestXlsx(t, header, rows)

	res, err := ParseFile(path, "")
	if err != nil {
		t.Fatalf("ParseFile: %v", err)
	}

	// 用 json.Marshal 反序列化一遍看字面 JSON，确保没 null
	raw, err := json.Marshal(res)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	s := string(raw)
	if strings.Contains(s, `"users":null`) {
		t.Errorf("users JSON is null, want []: %s", s)
	}
	if strings.Contains(s, `"errors":null`) {
		t.Errorf("errors JSON is null, want []: %s", s)
	}
	if strings.Contains(s, `"errors":null`) {
		// 同时检查每行 row 的 errors 字段
	}

	// 逐字段检查
	for i, u := range res.Users {
		if u.Errors == nil {
			t.Errorf("users[%d].Errors is nil", i)
		}
		if res.Errors == nil {
			t.Errorf("res.Errors is nil")
		}
	}
}
