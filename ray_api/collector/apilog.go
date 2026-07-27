package collector

import (
	"sync"
	"time"
)

// APILogEntry 是单个 API 日志条目（同时承载后端采集生命周期和前端用户事件）。
type APILogEntry struct {
	Ts      int64  `json:"ts"`      // 毫秒时间戳
	Source  string `json:"source"`  // "backend" 或 "frontend"
	Cluster string `json:"cluster"` // 集群 ID，无关时为空
	Phase   string `json:"phase"`   // 阶段：summary / detail / refresh / tab / cluster ...
	Message string `json:"message"` // 自由文本
}

const apiLogCapacity = 1000

// APILog 是线程安全的 ring buffer，保存最近 apiLogCapacity 条事件。
// 满了之后丢最老的。
type APILog struct {
	mu   sync.Mutex
	buf  []APILogEntry
	next int
	full bool
}

func NewAPILog() *APILog {
	return &APILog{buf: make([]APILogEntry, 0, apiLogCapacity)}
}

// Append 追加一条事件。自动填时间戳。
func (l *APILog) Append(source, cluster, phase, message string) {
	e := APILogEntry{
		Ts:      time.Now().UnixMilli(),
		Source:  source,
		Cluster: cluster,
		Phase:   phase,
		Message: message,
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	if !l.full && len(l.buf) < apiLogCapacity {
		l.buf = append(l.buf, e)
		l.next = len(l.buf) % apiLogCapacity
		if l.next == 0 && len(l.buf) == apiLogCapacity {
			l.full = true
		}
		return
	}
	// 满了，覆盖最老的
	l.buf[l.next] = e
	l.next = (l.next + 1) % apiLogCapacity
	l.full = true
}

// Recent 返回最近 limit 条（最新在前）。limit<=0 返全部。
func (l *APILog) Recent(limit int) []APILogEntry {
	l.mu.Lock()
	defer l.mu.Unlock()
	if !l.full {
		out := make([]APILogEntry, len(l.buf))
		copy(out, l.buf)
		reverseAPILog(out)
		return applyAPILogLimit(out, limit)
	}
	// 满了：按时间序拼接 [next..end) + [0..next)
	ordered := make([]APILogEntry, 0, apiLogCapacity)
	ordered = append(ordered, l.buf[l.next:]...)
	ordered = append(ordered, l.buf[:l.next]...)
	reverseAPILog(ordered)
	return applyAPILogLimit(ordered, limit)
}

func reverseAPILog(s []APILogEntry) {
	for i, j := 0, len(s)-1; i < j; i, j = i+1, j-1 {
		s[i], s[j] = s[j], s[i]
	}
}

func applyAPILogLimit(s []APILogEntry, limit int) []APILogEntry {
	if limit > 0 && len(s) > limit {
		return s[:limit]
	}
	return s
}
