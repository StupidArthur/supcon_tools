package monitor

import (
	"context"
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
	TenantTimeout  = 5 * time.Second  // 单个租户单请求预算
	RoundBudget    = 10 * time.Second // 整轮预算
	MaxAbnormalKpt = 2                // 内存保留的最近异常周期数
)

// Service 提供数据源监控：数据源存活 + 33 位号质量检查。
type Service struct {
	cfg     *team.Config
	session *cubauth.Session

	mu       sync.Mutex
	clients  map[string]*envClient // key=tenantID
	abnormal []Cycle               // 最近 N 次异常周期快照（FIFO 保 max）
	last     Snapshot              // 最新一轮快照（供前端切入时立即拉取）
	hasLast  bool
}

func New(cfg *team.Config, session *cubauth.Session) *Service {
	return &Service{cfg: cfg, session: session, clients: map[string]*envClient{}}
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

// Scan 扫描测试租户一：数据源 alive（ds-info）+ 全部位号质量（cub-data readValues）。
func (s *Service) Scan(ctx context.Context) (*Report, error) {
	env, err := cubauth.PickAuthEnv(s.cfg)
	if err != nil {
		return nil, err
	}
	return s.scanEnv(ctx, env), nil
}

// pollAll 并发扫描全部租户，返回当前轮结果（按配置顺序）。
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
			tctx, cancel := context.WithTimeout(ctx, TenantTimeout)
			defer cancel()
			reports[i] = *s.scanEnv(tctx, env)
		}(i, env)
	}
	wg.Wait()
	return &Cycle{
		At:      time.Now().Format(time.RFC3339),
		DurMs:   time.Since(start).Milliseconds(),
		Reports: reports,
	}
}

// abnormalHistory 若本轮存在异常，则追加异常快照并裁剪到 MaxAbnormalKpt。
func (s *Service) recordAbnormal(cycle *Cycle) []Cycle {
	s.mu.Lock()
	defer s.mu.Unlock()
	rpt := cycle.AbnormalReports()
	if len(rpt) == 0 {
		return s.snapshotAbnormalLocked()
	}
	ab := Cycle{
		At:      cycle.At,
		DurMs:   cycle.DurMs,
		Reports: rpt,
	}
	s.abnormal = append(s.abnormal, ab)
	if len(s.abnormal) > MaxAbnormalKpt {
		s.abnormal = s.abnormal[len(s.abnormal)-MaxAbnormalKpt:]
	}
	return s.snapshotAbnormalLocked()
}

func (s *Service) snapshotAbnormalLocked() []Cycle {
	out := make([]Cycle, len(s.abnormal))
	copy(out, s.abnormal)
	return out
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
				continue // 上轮未完，跳过本轮
			}
			busy = true
			func() {
				defer func() { busy = false }()
				cycle := s.pollAll(ctx)
				ab := s.recordAbnormal(cycle)
				for _, r := range cycle.AbnormalReports() {
					log.Printf("[monitor] 异常租户 %s(%s): %s", r.Name, r.TenantID, r.Error)
				}
				snap := Snapshot{Cycle: *cycle, AbnormalCycles: ab}
				s.mu.Lock()
				s.last = snap
				s.hasLast = true
				s.mu.Unlock()
				emit(snap)
			}()
		}
	}
}

// scanEnv 扫描单个租户：数据源 alive + 位号质量，结果尽量部分返回。
func (s *Service) scanEnv(ctx context.Context, env *team.Env) *Report {
	rep := &Report{
		Name:     env.Name,
		TenantID: env.TenantID,
		BadTags:  []string{},
	}
	c := s.client(env)
	// 数据源
	found, alive, name, url, err := c.scanDs(ctx, wantURL(env))
	if err != nil {
		rep.Error = appendErr(rep.Error, "查数据源失败: "+err.Error())
	} else if !found {
		rep.Error = appendErr(rep.Error, "未找到数据源: "+wantURL(env))
	} else {
		rep.DsFound = true
		rep.DsAlive = alive
		rep.DsName = name
		rep.DsTarUrl = url
	}
	// 2. 位号
	if ctx.Err() == nil {
		res, err := c.scanData(ctx)
		if err != nil {
			rep.Error = appendErr(rep.Error, "读位号失败: "+err.Error())
		} else {
			total, good, badTags, perr := ParseQualities(res)
			if perr != nil {
				rep.Error = appendErr(rep.Error, perr.Error())
			} else {
				rep.TagTotal = total
				rep.TagGood = good
				rep.BadTags = badTags
			}
			rep.SampleValue, rep.SampleTime = ExtractSample(res)
		}
	}
	return rep
}

// Convenience: 复用 appendErr。
func appendErr(cur, msg string) string {
	if cur == "" {
		return msg
	}
	return cur + "；" + msg
}