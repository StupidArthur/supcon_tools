package main

import (
	"embed"
	"log"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"

	"tpt_rw_gui/internal/app"
)

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	container, err := app.NewContainer()
	if err != nil {
		log.Fatal(err)
	}
	container.Wire()

	if err := wails.Run(&options.App{
		Title:  "TPT 值读写验证",
		Width:  1280,
		Height: 960,
		AssetServer: &assetserver.Options{
			Assets: assets,
		},
		OnStartup:  container.Lifecycle.Startup,
		OnShutdown: container.Lifecycle.Shutdown,
		Bind: []interface{}{
			container.SessionBinding,
			container.RWBinding,
		},
	}); err != nil {
		log.Fatal(err)
	}
}
