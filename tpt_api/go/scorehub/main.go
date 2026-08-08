package main

import (
	"embed"
	"io"
	"log"
	"os"
	"path/filepath"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"

	"scorehub/internal/app"
)

//go:embed all:frontend/dist
var assets embed.FS

// initLogging 在 exe 同目录打开 supcon_cup_manager.log（追加），同时输出到 stderr（dev 可见）。
func initLogging() {
	log.SetFlags(log.LstdFlags)
	var writers []io.Writer
	if exe, err := os.Executable(); err == nil {
		p := filepath.Join(filepath.Dir(exe), "supcon_cup_manager.log")
		if f, err := os.OpenFile(p, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644); err == nil {
			writers = append(writers, f)
		}
	}
	writers = append(writers, os.Stderr)
	log.SetOutput(io.MultiWriter(writers...))
}

func main() {
	initLogging()

	container, err := app.NewContainer()
	if err != nil {
		log.Fatal(err)
	}

	err = wails.Run(&options.App{
		Title:     "SUPCON CUP 2026 运维",
		Width:     1600,
		Height:    900,
		MinWidth:  1200,
		MinHeight: 600,
		AssetServer: &assetserver.Options{
			Assets: assets,
		},
		BackgroundColour: &options.RGBA{R: 247, G: 246, B: 243, A: 1},
		OnStartup:        container.Lifecycle.Startup,
		OnShutdown:       container.Lifecycle.Shutdown,
		Bind: []interface{}{
			container.TeamBinding,
			container.RankingBinding,
			container.BatchBinding,
			container.PersonalBinding,
			container.MonitorBinding,
		},
	})
	if err != nil {
		log.Fatal(err)
	}
}
