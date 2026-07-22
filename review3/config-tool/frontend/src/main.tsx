import React, { Component, type ErrorInfo, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import '@xyflow/react/dist/style.css'
import './style.css'
import App from './App'

/** 捕获渲染期异常，避免整页白屏无提示。 */
class RootErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('UI crash:', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 24, fontFamily: 'sans-serif', color: '#111' }}>
          <h1 style={{ fontSize: 18, marginBottom: 8 }}>界面加载失败</h1>
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, color: '#b91c1c' }}>
            {this.state.error.message}
          </pre>
        </div>
      )
    }
    return this.props.children
  }
}

const container = document.getElementById('root')
if (!container) {
  document.body.innerHTML =
    '<div style="padding:24px;font-family:sans-serif">缺少 #root，无法挂载界面</div>'
} else {
  createRoot(container).render(
    <React.StrictMode>
      <RootErrorBoundary>
        <App />
      </RootErrorBoundary>
    </React.StrictMode>,
  )
}
