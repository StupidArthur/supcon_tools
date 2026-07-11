import { useMemo, useCallback, useRef, useEffect } from 'react'
import { useStore } from '../store/useStore'
import * as api from '../lib/api'

function ParamInput({
  label,
  value,
  onChange,
}: {
  label: string
  value: number
  onChange: (v: number) => void
}) {
  const timerRef = useRef<ReturnType<typeof setTimeout>>()

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const v = parseFloat(e.target.value)
      if (isNaN(v)) return
      clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => onChange(v), 300)
    },
    [onChange]
  )

  useEffect(() => {
    return () => clearTimeout(timerRef.current)
  }, [])

  return (
    <div className="flex items-center gap-2 mb-1.5">
      <span className="text-xs text-gray-400 w-10 flex-shrink-0 font-mono">
        {label}
      </span>
      <input
        className="flex-1 px-2 py-1 bg-gray-700 text-gray-100 border border-gray-600 rounded text-xs font-mono focus:outline-none focus:border-blue-500"
        type="number"
        defaultValue={value}
        onChange={handleChange}
        step="any"
      />
    </div>
  )
}

export default function ParamPanel() {
  const { meta, instanceName } = useStore()

  const groups = useMemo(() => {
    if (!meta?.meta) return []
    const map = new Map<string, Array<{ param: string; desc: string; val: number }>>()
    for (const [key, info] of Object.entries(meta.meta)) {
      const inst = info.instance
      const param = info.param
      if (!param) continue
      if (!map.has(inst)) map.set(inst, [])
      map.get(inst)!.push({
        param,
        desc: info.description,
        val: 0,
      })
    }
    return Array.from(map.entries())
  }, [meta])

  const handleParamChange = useCallback(
    (name: string, param: string, value: number) => {
      api.setParam(name, param, value)
    },
    []
  )

  return (
    <div className="w-72 bg-gray-800 border-r border-gray-700 overflow-y-auto flex-shrink-0">
      <div className="px-3 py-2 text-xs font-semibold text-gray-300 uppercase tracking-wider border-b border-gray-700">
        参数面板
      </div>
      <div className="p-3 space-y-4">
        {groups.length === 0 && (
          <p className="text-xs text-gray-500">暂无参数</p>
        )}
        {groups.map(([name, params]) => (
          <div key={name}>
            <div className="text-xs font-medium text-gray-300 mb-2">
              {name}
            </div>
            {params.map((p) => (
              <ParamInput
                key={p.param}
                label={p.param}
                value={p.val}
                onChange={(v) => handleParamChange(name, p.param, v)}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
