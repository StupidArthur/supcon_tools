package task

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	tptapi "github.com/yzc/tpt_api"

	"scorehub/internal/team"
)

// Service 提供选手租户的调度任务统计（全量遍历，只读）。
type Service struct {
	cfg *team.Config
}

func New(cfg *team.Config) *Service {
	return &Service{cfg: cfg}
}

// Stats 遍历所有选手租户，统计每个租户的任务总数与启用数（jobStatus=1）。
// 返回按启用数升序排列的结果；拉取失败的租户标记为错误。
func (s *Service) Stats(ctx context.Context) []TeamTaskStats {
	envs := team.OrderedEnvs(s.cfg)
	out := make([]TeamTaskStats, 0, len(envs))
	var mu sync.Mutex
	var wg sync.WaitGroup
	sem := make(chan struct{}, 6)
	for _, env := range envs {
		if env.Type == "测试" {
			continue
		}
		env := env
		wg.Add(1)
		go func() {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			stats := s.statsOne(ctx, env)
			mu.Lock()
			out = append(out, stats)
			mu.Unlock()
		}()
	}
	wg.Wait()

	// 按启用数升序；启用数相同的按序号（队伍顺序）排序。
	teamList := team.ListTeams(s.cfg)
	seqMap := make(map[string]int, len(teamList))
	for _, t := range teamList {
		seqMap[t.TenantID] = t.Seq
	}
	for i := range out {
		out[i].Seq = seqMap[out[i].TenantID]
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Enabled != out[j].Enabled {
			return out[i].Enabled < out[j].Enabled
		}
		return out[i].Seq < out[j].Seq
	})
	return out
}

func (s *Service) statsOne(ctx context.Context, env *team.Env) TeamTaskStats {
	stats := TeamTaskStats{Name: env.Name, TenantID: env.TenantID}
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()

	tc, err := tptapi.LoginSubject(s.cfg.BaseURL, s.cfg.Admin.Username, s.cfg.Admin.Password, env.TenantID, 30*time.Second)
	if err != nil {
		return stats
	}
	tasks, err := tc.GetAllScheduleTasks(ctx, 200)
	if err != nil {
		return stats
	}
	stats.Total = len(tasks)
	var parts []string
	for _, t := range tasks {
		if t.JobStatus != 1 {
			continue
		}
		stats.Enabled++
		parts = append(parts, scheduleExpr(t))
	}
	stats.EnabledDetail = strings.Join(parts, " | ")
	return stats
}

// scheduleExpr 返回任务调度表达式：优先 cron，否则 fixRate（秒）。
func scheduleExpr(t tptapi.ScheduleTask) string {
	if cron := strings.TrimSpace(t.CronExpression); cron != "" {
		return cron
	}
	if t.FixRate > 0 {
		return fmt.Sprintf("fix:%ds", t.FixRate)
	}
	return "?"
}
