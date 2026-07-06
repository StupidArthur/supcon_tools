package excel

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"

	"github.com/xuri/excelize/v2"
)

func TestWriteTemplate(t *testing.T) {
	var buf bytes.Buffer
	if err := WriteTemplate(&buf); err != nil {
		t.Fatalf("WriteTemplate: %v", err)
	}
	if buf.Len() == 0 {
		t.Fatal("output is empty")
	}

	// 写到临时文件，再用 excelize 读回来验证内容
	dir := t.TempDir()
	path := filepath.Join(dir, "template.xlsx")
	if err := os.WriteFile(path, buf.Bytes(), 0o644); err != nil {
		t.Fatalf("write: %v", err)
	}

	f, err := excelize.OpenFile(path)
	if err != nil {
		t.Fatalf("open template: %v", err)
	}
	defer f.Close()

	rows, err := f.GetRows(f.GetSheetName(0))
	if err != nil {
		t.Fatalf("GetRows: %v", err)
	}
	if len(rows) < 2 {
		t.Fatalf("template has only %d rows, want >= 2 (header + sample)", len(rows))
	}

	// 校验表头
	gotHeader := rows[0]
	if len(gotHeader) != len(TemplateHeaders) {
		t.Errorf("header cols = %d, want %d", len(gotHeader), len(TemplateHeaders))
	}
	for i, want := range TemplateHeaders {
		if i >= len(gotHeader) || gotHeader[i] != want {
			t.Errorf("header[%d] = %q, want %q", i, gotHeader[i], want)
		}
	}

	// 校验示例行
	gotSample := rows[1]
	if len(gotSample) != len(TemplateSample) {
		t.Errorf("sample cols = %d, want %d", len(gotSample), len(TemplateSample))
	}
	for i, want := range TemplateSample {
		if i >= len(gotSample) || gotSample[i] != want {
			t.Errorf("sample[%d] = %q, want %q", i, gotSample[i], want)
		}
	}
}

func TestWriteTemplate_ToFile(t *testing.T) {
	// 验证可以写到文件（SaveFileDialog 拿到的路径走这条路）
	dir := t.TempDir()
	path := filepath.Join(dir, "template.xlsx")
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	defer f.Close()

	if err := WriteTemplate(f); err != nil {
		t.Fatalf("WriteTemplate: %v", err)
	}

	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if info.Size() == 0 {
		t.Error("template file is empty")
	}
}