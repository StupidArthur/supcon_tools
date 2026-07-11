package main

import (
	"embed"

	"pid_debug_gui/internal/bindings"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
)

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	debugBinding := bindings.NewDebugBinding()

	err := wails.Run(&options.App{
		Title:  "PID 调试工具",
		Width:  1280,
		Height: 800,
		AssetServer: &assetserver.Options{
			Assets: assets,
		},
		BackgroundColour: &options.RGBA{R: 30, G: 30, B: 30, A: 1},
		OnStartup:        debugBinding.Startup,
		OnShutdown:       debugBinding.Shutdown,
		Bind: []interface{}{
			debugBinding,
		},
	})

	if err != nil {
		println("Error:", err.Error())
	}
}
