// Package batch 提供批量并发操作能力。
//
// 当前实现：
//   - BatchCreateUsers: 并发 N 个 CreateUser 调用，errgroup.SetLimit 控制并发度
//   - 每条完成后通过 OnProgress 回调给前端（包装成 Wails 事件 emit）
//   - 单条失败不中断整批，错误记入 Result.Error
//   - 支持 ctx 取消
//
// 设计依据：doc/design.md §3.3 + §5.1（runtime-safety）
package batch

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"

	"golang.org/x/sync/errgroup"

	"user-manager/internal/api"
)

// DefaultConcurrency 是默认并发上限（v1 默认值，与 doc/design.md §4 分歧 4 推荐一致）。
const DefaultConcurrency = 3

// MaxConcurrency 是并发硬上限（防止 caller 配错拖垮平台）。
const MaxConcurrency = 20

// CreateResult 单条 create 结果。
type CreateResult struct {
	Username string `json:"username"`
	NickName string `json:"nickName"`
	Row      int    `json:"row"`    // xlsx 行号；前端批量传入时定位用
	Success  bool   `json:"success"`
	Code     string `json:"code"`   // 平台返回的业务 code
	Msg      string `json:"msg"`    // 平台返回的业务 msg
	Error    string `json:"error"`  // 客户端错误（网络/解析）
}

// BatchProgress 是 OnProgress 回调的参数。
// 通过单一结构体传递，避免函数签名膨胀。
type BatchProgress struct {
	Done     int            `json:"done"`
	Failed   int            `json:"failed"`
	Total    int            `json:"total"`
	Last     *CreateResult  `json:"last"`     // 本次回调的最近一条结果
	Finished bool           `json:"finished"` // 是否整批结束
}

// BatchCreateUsers 并发执行 N 次 CreateUser。
//
//   - drafts: 待创建的草稿列表
//   - concurrency: 并发度，<=0 用 DefaultConcurrency；> MaxConcurrency 截到 MaxConcurrency
//   - onProgress: 每条完成（成功或失败）回调一次；onProgress=nil 时跳过
//
// 返回值：
//   - 所有 CreateResult（顺序与输入 drafts 一致；非并发安全由 caller 保证）
//   - error: 仅当 ctx 取消时返回 context.Canceled；单条业务失败不通过 error 返回，体现在 Result.Error
func BatchCreateUsers(
	ctx context.Context,
	c *api.Client,
	drafts []api.UserDraft,
	concurrency int,
	onProgress func(BatchProgress),
) ([]CreateResult, error) {
	if concurrency <= 0 {
		concurrency = DefaultConcurrency
	}
	if concurrency > MaxConcurrency {
		concurrency = MaxConcurrency
	}

	results := make([]CreateResult, len(drafts))
	var done, failed int64

	// errgroup 控制并发；SetLimit(N) 限流
	g, gctx := errgroup.WithContext(ctx)
	g.SetLimit(concurrency)

	for i := range drafts {
		d := drafts[i]
		idx := i
		g.Go(func() error {
			// ctx 取消则跳过
			if gctx.Err() != nil {
				return nil
			}
			r := CreateResult{
				Username: d.Username,
				NickName: d.NickName,
				Row:      idx + 2, // 默认对应 xlsx 第 i+2 行（表头 1 + 偏移）
			}
			st, err := c.CreateUser(gctx, d)
			if err != nil {
				r.Error = err.Error()
				// 尝试从 ErrAPI / ErrAuthError 提取 code/msg
				var apiErr *api.ErrAPI
				if errors.As(err, &apiErr) {
					r.Code = apiErr.Code
					r.Msg = apiErr.Msg
				}
				var authErr *api.ErrAuthError
				if errors.As(err, &authErr) {
					r.Code = authErr.Code
					r.Msg = authErr.Msg
				}
				atomic.AddInt64(&failed, 1)
			} else {
				r.Code = st.Code
				r.Msg = st.Msg
				if st.Code != "00000" {
					r.Error = st.Msg
					atomic.AddInt64(&failed, 1)
				} else {
					r.Success = true
				}
			}
			results[idx] = r
			atomic.AddInt64(&done, 1)

			if onProgress != nil {
				// 拷贝 r 给回调，避免外部读到后续修改
				lr := r
				onProgress(BatchProgress{
					Done:     int(atomic.LoadInt64(&done)),
					Failed:   int(atomic.LoadInt64(&failed)),
					Total:    len(drafts),
					Last:     &lr,
					Finished: int(atomic.LoadInt64(&done)) == len(drafts),
				})
			}
			return nil
		})
	}

	_ = g.Wait() // 单条失败不返回 error，errgroup 仅用于 ctx 取消信号
	return results, ctx.Err()
}

// 静默使用 sync.Mutex（保留扩展位）
var _ sync.Mutex
