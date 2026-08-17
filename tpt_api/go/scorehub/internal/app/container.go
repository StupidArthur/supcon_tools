package app

import (
	"scorehub/internal/batch"
	"scorehub/internal/bindings"
	"scorehub/internal/cubauth"
	"scorehub/internal/monitor"
	"scorehub/internal/personal"
	"scorehub/internal/ranking"
	"scorehub/internal/task"
	"scorehub/internal/team"
)

// Container 是唯一组合根，创建所有依赖。
type Container struct {
	Lifecycle       *Lifecycle
	TeamBinding     *bindings.TeamBinding
	RankingBinding  *bindings.RankingBinding
	BatchBinding    *bindings.BatchBinding
	PersonalBinding *bindings.PersonalBinding
	MonitorBinding  *bindings.MonitorBinding
	TaskBinding     *bindings.TaskBinding
}

func NewContainer() (*Container, error) {
	cfg, err := team.LoadConfig()
	if err != nil {
		return nil, err
	}

	session, err := cubauth.NewSession(cfg)
	if err != nil {
		return nil, err
	}

	teamBinding := bindings.NewTeamBinding(cfg)

	rankingService := ranking.New(cfg, session)
	rankingBinding := bindings.NewRankingBinding(rankingService)

	batchService := batch.New(cfg, session)
	batchBinding := bindings.NewBatchBinding(batchService)

	personalService := personal.New(cfg, session, rankingService)
	personalBinding := bindings.NewPersonalBinding(personalService)

	monitorService := monitor.New(cfg, session)
	monitorBinding := bindings.NewMonitorBinding(monitorService)

	taskService := task.New(cfg)
	taskBinding := bindings.NewTaskBinding(taskService)

	lifecycle := NewLifecycle(teamBinding, rankingBinding, batchBinding, personalBinding, monitorBinding, taskBinding)

	return &Container{
		Lifecycle:       lifecycle,
		TeamBinding:     teamBinding,
		RankingBinding:  rankingBinding,
		BatchBinding:    batchBinding,
		PersonalBinding: personalBinding,
		MonitorBinding:  monitorBinding,
		TaskBinding:     taskBinding,
	}, nil
}
