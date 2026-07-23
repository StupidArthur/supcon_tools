package main

import (
	"embed"
	"log"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"

	"config-tool/internal/app"
)

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	container, err := app.NewContainer()
	if err != nil {
		log.Fatal(err)
	}

	err = wails.Run(&options.App{
		Title:     "DataFactory 组态工具",
		Width:     1280,
		Height:    800,
		MinWidth:  960,
		MinHeight: 640,
		AssetServer: &assetserver.Options{
			Assets: assets,
		},
		BackgroundColour: &options.RGBA{R: 247, G: 246, B: 243, A: 1},
		OnStartup:        container.Lifecycle.Startup,
		OnShutdown:       container.Lifecycle.Shutdown,
		Bind: []interface{}{
			container.ComponentBinding,
			container.ConfigBinding,
			container.SystemBinding,
			container.TemplateConfigBinding,
			container.RealtimeProjectBinding,
			container.RealtimeRuntimeBinding,
		},
	})
	if err != nil {
		log.Fatal(err)
	}
}
