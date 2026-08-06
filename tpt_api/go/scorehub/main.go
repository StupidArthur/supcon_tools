package main

import (
	"embed"
	"log"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"

	"scorehub/internal/app"
)

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	container, err := app.NewContainer()
	if err != nil {
		log.Fatal(err)
	}

	err = wails.Run(&options.App{
		Title:     "SupCon Cup 2026 评分管理",
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
		},
	})
	if err != nil {
		log.Fatal(err)
	}
}
