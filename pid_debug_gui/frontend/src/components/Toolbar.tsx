import { useState, useCallback } from 'react'
import { useStore } from '../store/useStore'
import * as api from '../lib/api'

export default function Toolbar() {
  const {
    connectionState,
    baseUrl,
    setBaseUrl,
    setConnectionState,
    setInstanceName,
    setMeta,
    setDisplayVars,
    setStatus,
    pushSnapshot,
    reset,
    instanceName,
  } = useStore()

  const [urlInput, setUrlInput] = useState(baseUrl)
  const [exporting, setExporting] = useState(false)

  const handleConnect = useCallback(async () => {
    setConnectionState('connecting')
    const name = await api.connect(urlInput)
    if (!name) {
      setConnectionState('disconnected')
      return
    }
    setBaseUrl(urlInput)
    setInstanceName(name)
    setConnectionState('connected')

    const status = await api.getStatus()
    if (status) setStatus(status)

    const meta = await api.getMeta()
    if (meta) setMeta(meta)

    const disp = await api.getDisplayVariables()
    setDisplayVars(disp)

    // Subscribe to Go-side snapshot events (see DebugBinding)
    try {
      const { EventsOn } = await import('../../wailsjs/runtime/runtime')
      EventsOn('snapshot', (snap: Record<string, number | boolean>) => {
        pushSnapshot(snap)
      })
    } catch {
      // runtime not available in browser dev mode
    }

    // Load initial history
    const history = await api.getSnapshotHistory()
    for (const snap of history) {
      pushSnapshot(snap as Record<string, number | boolean>)
    }
  }, [urlInput, setConnectionState, setBaseUrl, setInstanceName, setStatus, setMeta, setDisplayVars, pushSnapshot])

  const handleDisconnect = useCallback(async () => {
    await api.disconnect()
    reset()
  }, [reset])

  const handleExport = useCallback(async () => {
    if (!instanceName) return
    setExporting(true)
    await api.exportCsv(`${instanceName}_export.csv`)
    setExporting(false)
  }, [instanceName])

  const isConnected = connectionState === 'connected'
  const isConnecting = connectionState === 'connecting'

  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-gray-800 border-b border-gray-700">
      <input
        className="flex-1 max-w-xs px-3 py-1.5 bg-gray-700 text-gray-100 border border-gray-600 rounded text-sm focus:outline-none focus:border-blue-500 disabled:opacity-50"
        placeholder="API 地址"
        value={urlInput}
        onChange={(e) => setUrlInput(e.target.value)}
        disabled={isConnected || isConnecting}
      />
      {!isConnected ? (
        <button
          className="px-4 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 text-white rounded transition-colors"
          onClick={handleConnect}
          disabled={isConnecting}
        >
          {isConnecting ? '连接中...' : '连接'}
        </button>
      ) : (
        <button
          className="px-4 py-1.5 text-sm bg-red-600 hover:bg-red-500 text-white rounded transition-colors"
          onClick={handleDisconnect}
        >
          断开
        </button>
      )}
      <span className="text-sm text-gray-400 ml-2">
        {instanceName && `实例: ${instanceName}`}
      </span>
      <div className="flex-1" />
      {isConnected && (
        <button
          className="px-4 py-1.5 text-sm bg-green-700 hover:bg-green-600 disabled:bg-gray-600 text-white rounded transition-colors"
          onClick={handleExport}
          disabled={exporting}
        >
          {exporting ? '导出中...' : '导出 CSV'}
        </button>
      )}
    </div>
  )
}
