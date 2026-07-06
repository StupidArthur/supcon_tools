package main

import (
	"context"
	"embed"
	"os/exec"
	stdruntime "runtime"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"

	"raymonitor/logx"
)

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	app := NewApp()
	err := wails.Run(&options.App{
		Title:     "Ray 集群监控",
		Width:     1180,
		Height:    780,
		MinWidth:  920,
		MinHeight: 620,
		AssetServer: &assetserver.Options{
			Assets: assets,
		},
		BackgroundColour: &options.RGBA{R: 255, G: 255, B: 255, A: 1}, // 浅色主题白底
		OnStartup:        app.startup,
		OnShutdown:       app.shutdown,
		Bind: []interface{}{
			app,
		},
	})
	if err != nil {
		logx.L().Error("wails run failed", "err", err)
	}
}

// openInFolder 用系统资源管理器打开目录（跨平台）。
func openInFolder(_ context.Context, path string) {
	if path == "" {
		return
	}
	var cmd *exec.Cmd
	switch stdruntime.GOOS {
	case "windows":
		cmd = exec.Command("explorer", path)
	case "darwin":
		cmd = exec.Command("open", path)
	default:
		cmd = exec.Command("xdg-open", path)
	}
	_ = cmd.Start()
}
