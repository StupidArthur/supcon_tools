package realtime

import "fmt"

type ValidationError struct {
	Code    string              `json:"code"`
	Message string              `json:"message"`
	Result  *ValidationResult   `json:"result,omitempty"`
}

func (e *ValidationError) Error() string {
	return fmt.Sprintf("[%s] %s", e.Code, e.Message)
}

func NewDuplicateError(result ValidationResult) *ValidationError {
	return &ValidationError{
		Code:    "DUPLICATE_INSTANCE_NAMES",
		Message: "实例名称重复",
		Result:  &result,
	}
}

func NewParseError(sourceID, sourceFile, detail string) *ValidationError {
	return &ValidationError{
		Code:    "DSL_PARSE_ERROR",
		Message: fmt.Sprintf("解析 %s 失败: %s", sourceFile, detail),
	}
}
