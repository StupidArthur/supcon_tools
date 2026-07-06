package main

import (
	"os"
	"path/filepath"
	"testing"
)

// TestLoadCSV_GBK 用仓库自带的 GBK 编码 camp.csv 验证 LoadCSV 能正确解码。
func TestLoadCSV_GBK(t *testing.T) {
	csvPath := filepath.Join("..", "camp.csv")
	records, err := LoadCSV(csvPath)
	if err != nil {
		t.Fatalf("LoadCSV 失败: %v", err)
	}
	if len(records) == 0 {
		t.Fatal("LoadCSV 返回 0 条记录，编码探测可能没生效")
	}
	first := records[0]
	if first.Name == "" {
		t.Errorf("第一条 Name 为空，列名匹配失败")
	}
	if first.Release != "是" && first.Release != "否" {
		t.Errorf("Release 字段异常: %q", first.Release)
	}
	t.Logf("OK 加载 %d 条，第一条: Name=%q Release=%q Cores=%q Replicas=%q Position=%q",
		len(records), first.Name, first.Release, first.Cores, first.Replicas, first.Position)
}

// TestLoadCSV_UTF8BOM 验证带 UTF-8 BOM 的 CSV 也能正确跳过 BOM 头并解码。
func TestLoadCSV_UTF8BOM(t *testing.T) {
	dir := t.TempDir()
	csvPath := filepath.Join(dir, "utf8_bom.csv")
	content := "\xEF\xBB\xBF算法名称,是否发布,核数,副本数,发布位置\n" +
		"TestAlgo1,是,2,3,GPU\n" +
		"TestAlgo2,否,1,1,CPU\n"
	if err := os.WriteFile(csvPath, []byte(content), 0644); err != nil {
		t.Fatal(err)
	}
	records, err := LoadCSV(csvPath)
	if err != nil {
		t.Fatalf("LoadCSV 失败: %v", err)
	}
	if len(records) != 2 {
		t.Fatalf("期望 2 条记录，得到 %d 条", len(records))
	}
	if records[0].Name != "TestAlgo1" {
		t.Errorf("第一条 Name=%q 期望 TestAlgo1", records[0].Name)
	}
}
