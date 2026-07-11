import { useStore } from '../store/useStore'

export default function StatusBar() {
  const { status, connectionState, safeState } = useStore()
  const isConnected = connectionState === 'connected'

  return (
    <div className="flex items-center gap-4 px-4 py-1.5 bg-gray-800 border-t border-gray-700 text-xs text-gray-400">
      <span className="flex items-center gap-1.5">
        <span
          className={`inline-block w-2 h-2 rounded-full ${
            isConnected
              ? safeState
                ? 'bg-red-500'
                : 'bg-green-500'
              : 'bg-gray-600'
          }`}
        />
        {isConnected
          ? safeState
            ? 'SAFE STATE'
            : '正常'
          : '未连接'}
      </span>
      {status && (
        <>
          <span>状态: {status.mode}</span>
          <span>周期: {status.cycle_count}</span>
          <span>
            模拟时间: {status.sim_time.toFixed(1)}s
          </span>
          {status.consecutive_failures > 0 && (
            <span className="text-yellow-500">
              连续失败: {status.consecutive_failures}
            </span>
          )}
        </>
      )}
    </div>
  )
}
