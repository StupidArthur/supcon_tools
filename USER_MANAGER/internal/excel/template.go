package excel

import (
	"fmt"
	"io"

	"github.com/xuri/excelize/v2"
)

// TemplateHeaders 是导出给前端 / 测试 / 文档用的常量，避免重复定义。
var TemplateHeaders = []string{"username", "password", "nickName", "email", "phone"}

// TemplateSample 是模板里的 1 行示例，方便用户复制后修改。
// 密码是明显的占位符（Init@2026），真实环境必须改。
var TemplateSample = []string{"zhangsan", "Init@2026", "张三", "zhangsan@example.com", "13800138000"}

// WriteTemplate 把批量创建模板写到 w，包含表头 + 1 行示例。
//
// 调用方负责选好输出位置（通常是 SaveFileDialog 拿到的路径对应的文件）。
func WriteTemplate(w io.Writer) error {
	f := excelize.NewFile()
	defer f.Close()

	sheet := f.GetSheetName(0)

	// 表头（行 1）
	if err := f.SetSheetRow(sheet, "A1", &TemplateHeaders); err != nil {
		return fmt.Errorf("set header: %w", err)
	}

	// 示例行（行 2）— 用户可复制
	if err := f.SetSheetRow(sheet, "A2", &TemplateSample); err != nil {
		return fmt.Errorf("set sample row: %w", err)
	}

	// 列宽（让 username/password 不被截）
	colWidths := map[string]float64{"A": 16, "B": 16, "C": 16, "D": 24, "E": 14}
	for col, w := range colWidths {
		_ = f.SetColWidth(sheet, col, col, w)
	}

	if _, err := f.WriteTo(w); err != nil {
		return fmt.Errorf("write xlsx: %w", err)
	}
	return nil
}