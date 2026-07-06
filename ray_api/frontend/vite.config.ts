import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// Wails 前端配置：@ 别名指向 src，Vite 5。
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    // Wails dev 模式下由 wails 注入 host，监听全部
    host: '0.0.0.0',
    port: 5173,
  },
})
