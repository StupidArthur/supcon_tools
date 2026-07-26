//go:build wails_generate

// wails_generate 模式：仅用于 wails generate module 生成 TypeScript 绑定。
// 不启动服务，不运行 wails GUI。
package main

func main() {
	// 空的 main 函数：wails generate module 只需要编译入口存在
	// 实际绑定信息从 Bind 列表提取（但 wails_generate 模式下我们不需要）
}