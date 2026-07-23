package realtime

import "fmt"

// 统一错误代码（阶段 10）。前端依据 Code 做业务判断，不依赖中文消息字符串。
const (
	ErrProjectNotFound   = "REALTIME_PROJECT_NOT_FOUND"
	ErrCompileFailed     = "REALTIME_COMPILE_FAILED"
	ErrStartFailed       = "REALTIME_START_FAILED"
	ErrSessionConflict   = "REALTIME_SESSION_CONFLICT"
	ErrSessionNotRunning = "REALTIME_SESSION_NOT_RUNNING"
	ErrTagNotFound       = "REALTIME_TAG_NOT_FOUND"
	ErrForceInvalid      = "REALTIME_FORCE_INVALID"
	ErrAlarmInvalid      = "REALTIME_ALARM_INVALID"
	ErrDashboardInvalid  = "REALTIME_DASHBOARD_INVALID"
	ErrAPIUnavailable    = "REALTIME_API_UNAVAILABLE"
	ErrDuplicateNames    = "DUPLICATE_INSTANCE_NAMES"
	ErrDSLParse          = "DSL_PARSE_ERROR"
)

// RealtimeError 是实时模块的统一结构化错误。
type RealtimeError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

func (e *RealtimeError) Error() string {
	return fmt.Sprintf("[%s] %s", e.Code, e.Message)
}

func NewError(code, message string) *RealtimeError {
	return &RealtimeError{Code: code, Message: message}
}

type ValidationError struct {
	Code    string            `json:"code"`
	Message string            `json:"message"`
	Result  *ValidationResult `json:"result,omitempty"`
}

func (e *ValidationError) Error() string {
	return fmt.Sprintf("[%s] %s", e.Code, e.Message)
}

func NewDuplicateError(result ValidationResult) *ValidationError {
	return &ValidationError{
		Code:    ErrDuplicateNames,
		Message: "实例名称重复",
		Result:  &result,
	}
}

func NewParseError(sourceID, sourceFile, detail string) *ValidationError {
	return &ValidationError{
		Code:    ErrDSLParse,
		Message: fmt.Sprintf("解析 %s 失败: %s", sourceFile, detail),
	}
}
