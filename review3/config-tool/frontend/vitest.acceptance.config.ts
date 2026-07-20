import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const rootDir = path.dirname(fileURLToPath(import.meta.url))

/**
 * Reviewer-owned acceptance suite config.
 * Independent from src/** unit tests; business agents must not weaken these.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.join(rootDir, 'src'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: [path.join(rootDir, 'acceptance/setup.ts')],
    include: ['acceptance/**/*.acceptance.test.{ts,tsx}'],
  },
})
