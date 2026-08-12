package monitor

import (
	"context"
	"fmt"
	"log"
	"sync"
	"time"

	"scorehub/internal/cubauth"
	"scorehub/internal/team"
)

// 轮询参数。
const (
	PollInterval   = 5 * time.Second
	PollConcurrent = 6
	TenantTimeout  = 5 * time.Second // 单个租户单请求预算
)

// tenantState 是单个租户跨周期的异常状态机。
type tenantState struct {
	subAPIFailure SubAbnormal
	subDsNotFound SubAbnormal
	subDsOffline  SubAbnormal
	subTagBad     SubAbnormal
	subValueStale SubAbnormal

	apiFailCount int
	apiOKCount   int
	staleCount   int
	lastValue    string

	lastAbnType      int
	lastAbnSince     string
	lastAbnDetail    string
	lastAbnConfirmed bool
}

func (st *tenantState) isAbnormal() bool {
	return st.subAPIFailure.Active || st.subDsNotFound.Active ||
		st.subDsOffline.Active || st.subTagBad.Active || st.subValueStale.Active
}

// Service 提供数据源监控：数据源存活 + 位号质量检查 + 异常状态机。
type Service struct {
	cfg     *team.Config
	session *cubauth.Session

	mu      sync.Mutex
	clients map[string]*envClient    // key=tenantID
	states  map[string]*tenantState  // key=tenantID
	last    Snapshot                 // 最新一轮快照
	hasLast bool
}

func New(cfg *team.Config, session *cubauth.Session) *Service {
	return &Service{
		cfg:     cfg,
		session: session,
		clients: map[string]*envClient{},
		states:  map[string]*tenantState{},
	}
}

// client 获取（或创建）某租户的客户端池。
func (s *Service) client(env *team.Env) *envClient {
	s.mu.Lock()
	defer s.mu.Unlock()
	c, ok := s.clients[env.TenantID]
	if !ok {
		c = &envClient{
			env:       env,
			base:      s.cfg.BaseURL,
			adminUser: s.cfg.Admin.Username,
			adminPass: s.cfg.Admin.Password,
		}
		s.clients[env.TenantID] = c
	}
	return c
}

// Scan 扫描测试租户一（一次性，不走状态机）。
func (s *Service) Scan(ctx context.Context) (*Report, error) {
	env, err := cubauth.PickAuthEnv(s.cfg)
	if err != nil {
		return nil, err
	}
	rep, _, _ := s.scanEnv(ctx, env)
	return rep, nil
}

// pollAll 并发扫描全部租户并更新状态机，返回当前轮结果。
func (s *Service) pollAll(ctx context.Context) *Cycle {
	envs := sortEnvs(s.cfg)
	start := time.Now()
	sem := make(chan struct{}, PollConcurrent)
	reports := make([]Report, len(envs))
	var wg sync.WaitGroup
	for i, env := range envs {
		wg.Add(1)
		sem <- struct{}{}
		go func(i int, env *team.Env) {
			defer wg.Done()
			defer func() { <-sem }()
			rep, dsErr, dataErr := s.scanEnv(ctx, env)
			s.updateState(env, rep, dsErr, dataErr)
			reports[i] = *rep
		}(i, env)
	}
	wg.Wait()
	return &Cycle{
		At:      time.Now().Format(time.RFC3339),
		DurMs:   time.Since(start).Milliseconds(),
		Reports: reports,
	}
}

// Latest 返回最新一轮快照（无数据时 ok=false）。
func (s *Service) Latest() (Snapshot, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.last, s.hasLast
}

// RunPolling 周期性扫描并把快照发给回调；ctx 取消即停止。
func (s *Service) RunPolling(ctx context.Context, interval time.Duration, emit func(Snapshot)) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	busy := false
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if busy {
				continue
			}
			busy = true
			func() {
				defer func() { busy = false }()
				cycle := s.pollAll(ctx)
				snap := Snapshot{Cycle: *cycle}
				s.mu.Lock()
				s.last = snap
				s.hasLast = true
				s.mu.Unlock()
				emit(snap)
			}()
		}
	}
}

// ConfirmAbnormal 确认某租户的上一次异常（仅当总异常已消失时可调用）。
func (s *Service) ConfirmAbnormal(tenantID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	st, ok := s.states[tenantID]
	if !ok {
		return fmt.Errorf("租户不存在")
	}
	if st.isAbnormal() {
		return fmt.Errorf("当前仍有异常，无法确认")
	}
	if st.lastAbnType == AbnNone {
		return fmt.Errorf("无历史异常")
	}
	st.lastAbnConfirmed = true
	return nil
}

// updateState 把本轮扫描结果喂入租户状态机，更新子异常并回填 Report。
func (s *Service) updateState(env *team.Env, rep *Report, dsErr, dataErr error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	st, ok := s.states[env.TenantID]
	if !ok {
		st = &tenantState{}
		s.states[env.TenantID] = st
	}
	now := time.Now().Format(time.RFC3339)
	apiFailed := dsErr != nil || dataErr != nil

	if apiFailed {
		st.apiFailCount++
		st.apiOKCount = 0
		st.staleCount = 0
		st.lastValue = ""
		if st.apiFailCount >= 2 && !st.subAPIFailure.Active {
			st.subAPIFailure = SubAbnormal{Active: true, Since: now, Detail: fmt.Sprintf("连续%d轮API调用失败", st.apiFailCount)}
			log.Printf("[monitor] 异常 %s(%s): API异常(连续%d轮调用失败)", env.Name, env.TenantID, st.apiFailCount)
		}
	} else {
		st.apiFailCount = 0
		st.apiOKCount++

		// API异常：连续3轮成功后消失
		if st.subAPIFailure.Active && st.apiOKCount >= 3 {
			s.clearSub(env, st, AbnAPIFailure, &st.subAPIFailure)
		}

		// 数据源缺失 / 离线（需 scanDs 成功）
		if dsErr == nil {
			if !rep.DsFound {
				if !st.subDsNotFound.Active {
					st.subDsNotFound = SubAbnormal{Active: true, Since: now, Detail: "未找到数据源"}
					log.Printf("[monitor] 异常 %s(%s): 数据源缺失", env.Name, env.TenantID)
				}
			} else {
				s.clearSub(env, st, AbnDsNotFound, &st.subDsNotFound)
				if !rep.DsAlive {
					if !st.subDsOffline.Active {
						st.subDsOffline = SubAbnormal{Active: true, Since: now, Detail: "数据源离线"}
						log.Printf("[monitor] 异常 %s(%s): 数据源离线", env.Name, env.TenantID)
					}
				} else {
					s.clearSub(env, st, AbnDsOffline, &st.subDsOffline)
				}
			}
		}

		// 位号异常 / 值停滞（需 scanData 成功）
		if dataErr == nil {
			if rep.TagTotal != len(TagNames) || rep.TagGood != len(TagNames) {
				if !st.subTagBad.Active {
					st.subTagBad = SubAbnormal{Active: true, Since: now, Detail: fmt.Sprintf("位号%d/%d GOOD", rep.TagGood, rep.TagTotal)}
					log.Printf("[monitor] 异常 %s(%s): 位号异常(%d/%d GOOD)", env.Name, env.TenantID, rep.TagGood, rep.TagTotal)
				}
			} else {
				s.clearSub(env, st, AbnTagBad, &st.subTagBad)
			}

			if rep.SampleValue != "" {
				if st.lastValue != "" && rep.SampleValue == st.lastValue {
					st.staleCount++
				} else {
					st.staleCount = 0
				}
				st.lastValue = rep.SampleValue
				if st.staleCount >= 2 {
					if !st.subValueStale.Active {
						st.subValueStale = SubAbnormal{Active: true, Since: now, Detail: fmt.Sprintf("采样值%s连续%d轮未变", rep.SampleValue, st.staleCount)}
						log.Printf("[monitor] 异常 %s(%s): 值停滞(%s连续%d轮未变)", env.Name, env.TenantID, rep.SampleValue, st.staleCount)
					}
				} else {
					s.clearSub(env, st, AbnValueStale, &st.subValueStale)
				}
			}
		}
	}

	// 回填 Report 状态字段
	rep.SubAPIFailure = st.subAPIFailure
	rep.SubDsNotFound = st.subDsNotFound
	rep.SubDsOffline = st.subDsOffline
	rep.SubTagBad = st.subTagBad
	rep.SubValueStale = st.subValueStale
	rep.Abnormal = st.isAbnormal()
	rep.LastAbnType = st.lastAbnType
	rep.LastAbnSince = st.lastAbnSince
	rep.LastAbnDetail = st.lastAbnDetail
	rep.LastAbnConfirmed = st.lastAbnConfirmed
}

// clearSub 清除一个子异常并记录为上一次异常。
func (s *Service) clearSub(env *team.Env, st *tenantState, abnType int, sub *SubAbnormal) {
	if sub.Active {
		st.lastAbnType = abnType
		st.lastAbnSince = sub.Since
		st.lastAbnDetail = sub.Detail
		st.lastAbnConfirmed = false
		log.Printf("[monitor] 恢复 %s(%s): %s", env.Name, env.TenantID, AbnLabels[abnType])
		*sub = SubAbnormal{}
	}
}

// scanEnv 扫描单个租户，返回 Report 及 scanDs/scanData 的错误。
func (s *Service) scanEnv(ctx context.Context, env *team.Env) (*Report, error, error) {
	rep := &Report{
		Name:     env.Name,
		TenantID: env.TenantID,
		BadTags:  []string{},
	}
	c := s.client(env)
	var dsErr, dataErr error

	// 1. 数据源（独立超时）
	dsCtx, dsCancel := context.WithTimeout(ctx, TenantTimeout)
	defer dsCancel()
	found, alive, name, url, err := c.scanDs(dsCtx, wantURL(env))
	if err != nil {
		dsErr = err
		rep.Error = appendErr(rep.Error, "查数据源失败: "+err.Error())
	} else if !found {
		rep.Error = appendErr(rep.Error, "未找到数据源: "+wantURL(env))
	} else {
		rep.DsFound = true
		rep.DsAlive = alive
		rep.DsName = name
		rep.DsTarUrl = url
	}

	// 2. 位号（独立超时）
	tagCtx, tagCancel := context.WithTimeout(ctx, TenantTimeout)
	defer tagCancel()
	res, err := c.scanData(tagCtx)
	if err != nil {
		dataErr = err
		rep.Error = appendErr(rep.Error, "读位号失败: "+err.Error())
	} else {
		total, good, badTags, perr := ParseQualities(res)
		if perr != nil {
			dataErr = perr
			rep.Error = appendErr(rep.Error, perr.Error())
		} else {
			rep.TagTotal = total
			rep.TagGood = good
			rep.BadTags = badTags
		}
		rep.SampleValue, rep.SampleTime = ExtractSample(res)
	}
	return rep, dsErr, dataErr
}

func appendErr(cur, msg string) string {
	if cur == "" {
		return msg
	}
	return cur + "；" + msg
}
