import { useEffect, useState } from 'react'
import { realtimeProjectApi } from '../../lib/api'
import { useRuntimeStore } from '../runtime/useRuntimeStore'

interface ForceEntry {
  mode: string
  value?: number
}

interface Props {
  instanceName: string
  onBack: () => void
}

type OpKind = '' | 'fix' | 'sv' | 'quality'

export function RuntimeInstanceDetail({ instanceName, onBack }: Props) {
  const tagCatalog = useRuntimeStore((s) => s.tagCatalog)
  const latestFrame = useRuntimeStore((s) => s.latestFrame)
  const rawSnapshot = useRuntimeStore((s) => s.rawSnapshot)
  const connectionState = useRuntimeStore((s) => s.connectionState)
  const stale = useRuntimeStore((s) => s.stale)
  const apiHost = useRuntimeStore((s) => s.apiHost)
  const apiPort = useRuntimeStore((s) => s.apiPort)
  const runtimeName = useRuntimeStore((s) => s.runtimeName)
  const registerSubscription = useRuntimeStore((s) => s.registerSubscription)
  const unregisterSubscription = useRuntimeStore((s) => s.unregisterSubscription)

  const isConnected = connectionState === 'connected'
  const isConnecting = connectionState === 'connecting'
  const isRunning = isConnected || isConnecting
  const lastError = useRuntimeStore((s) => s.lastError)
  const hasRuntimeName = !!runtimeName

  const [forces, setForces] = useState<Record<string, ForceEntry>>({})
  const [qualities, setQualities] = useState<Record<string, string>>({})
  const [opKind, setOpKind] = useState<OpKind>('')
  const [opTargetTag, setOpTargetTag] = useState<string | null>(null)
  const [inputValue, setInputValue] = useState('')
  const [qualityValue, setQualityValue] = useState<'Good' | 'Uncertain' | 'Bad'>('Bad')
  const [error, setError] = useState<string | null>(null)

  // 当前实例 tags 列表（按 tag.instance === instanceName 过滤）
  // instanceName 是 PID/罐/阀门名；runtimeName 是本次运行的工程名，用于 REST 路径。
  // detail 页不复用 /api/instances/default/tags：useRuntimeStore.connect() 已用真实
  // runtimeName 调过 /api/instances/{runtimeName}/tags，存到 tagCatalog。
  const instanceTags = tagCatalog.filter((t) => t.instance === instanceName)


  // 订阅详情 tag
  useEffect(() => {
    if (instanceTags.length === 0) return
    const tagNames = instanceTags.map((t) => t.name)
    const id = setTimeout(() => {
      try {
        registerSubscription('instance-detail', tagNames)
      } catch (e) {
        setError(String(e))
      }
    }, 100)
    return () => clearTimeout(id)
  }, [instanceTags.map((t) => t.name).join('|'), registerSubscription])

  useEffect(() => {
    return () => {
      try {
        unregisterSubscription('instance-detail')
      } catch {
        // ignore
      }
    }
  }, [unregisterSubscription])

  // 拉 forces + qualities
  useEffect(() => {
    if (!isRunning) return
    let cancelled = false
    const refresh = async () => {
      try {
        const [f, q] = await Promise.all([
          realtimeProjectApi.getForces(apiHost, apiPort) as any,
          realtimeProjectApi.getQualities(apiHost, apiPort) as any,
        ])
        if (cancelled) return
        setForces(f?.forces || {})
        setQualities((q?.qualities as Record<string, string>) || {})
      } catch {
        // ignore
      }
    }
    void refresh()
    const id = setInterval(() => void refresh(), 2000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [apiHost, apiPort, isRunning])

  const readValue = (name: string): unknown => {
    if (latestFrame && Object.prototype.hasOwnProperty.call(latestFrame.values || {}, name)) {
      return (latestFrame.values as any)[name]
    }
    if (rawSnapshot && Object.prototype.hasOwnProperty.call(rawSnapshot, name)) {
      return (rawSnapshot as any)[name]
    }
    return null
  }

  const handleApply = async () => {
    if (!opTargetTag) return
    setError(null)
    try {
      if (opKind === 'fix') {
        if (!hasRuntimeName) {
          setError('运行连接信息尚未就绪')
          return
        }
        const v = Number(inputValue)
        if (!Number.isFinite(v)) {
          setError('固定值必须是有限数')
          return
        }
        await realtimeProjectApi.setForce(apiHost, apiPort, opTargetTag, 'fixed', v, undefined)
      } else if (opKind === 'sv') {
        if (!hasRuntimeName) {
          setError('运行连接信息尚未就绪')
          return
        }
        const v = Number(inputValue)
        if (!Number.isFinite(v)) {
          setError('设定值必须是有限数')
          return
        }
        await realtimeProjectApi.setRuntimeValue(apiHost, apiPort, runtimeName, opTargetTag, v)
      } else if (opKind === 'quality') {
        await realtimeProjectApi.setQuality(apiHost, apiPort, opTargetTag, qualityValue)
      }
      setOpKind('')
      setOpTargetTag(null)
      setInputValue('')
    } catch (e: any) {
      setError(String(e))
    }
  }

  const handleClear = async (tag: string, kind: 'fix' | 'quality') => {
    try {
      if (kind === 'fix') {
        await realtimeProjectApi.clearForce(apiHost, apiPort, tag)
      } else {
        await realtimeProjectApi.clearQuality(apiHost, apiPort, tag)
      }
    } catch (e: any) {
      setError(String(e))
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="runtime-instance-detail">
      <div className="flex items-center gap-2 border-b border-border pb-2">
        <button
          type="button"
          onClick={onBack}
          className="rounded-md border border-border px-2 py-0.5 text-xs hover:bg-secondary"
          data-testid="runtime-detail-back"
        >
          ← 返回实例列表
        </button>
        <div className="text-sm font-medium">当前实例：{instanceName}</div>
        {!isRunning ? (
          <div className="ml-2 rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800" data-testid="runtime-detail-not-running">
            服务尚未启动
          </div>
        ) : stale ? (
          <div className="ml-2 rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800">数据已过期</div>
        ) : null}
      </div>

      {connectionState === 'error' || (lastError && !isRunning) ? (
        <div className="mt-4 text-sm text-destructive" data-testid="runtime-detail-error">
          {lastError}
        </div>
      ) : !isRunning ? (
        <div className="mt-4 text-sm text-muted-foreground" data-testid="runtime-detail-empty">
          服务尚未启动，暂无实时参数。
        </div>
      ) : lastError ? (
        <div className="mt-4 text-sm text-destructive" data-testid="runtime-detail-error">
          {lastError}
        </div>
      ) : isConnecting ? (
        <div className="mt-4 text-sm text-muted-foreground" data-testid="runtime-detail-empty">
          正在加载实例参数…
        </div>
      ) : instanceTags.length === 0 ? (
        <div className="mt-4 text-sm text-muted-foreground" data-testid="runtime-detail-empty">
          当前实例没有可用参数。
        </div>
      ) : (
        <div className="mt-2 min-h-0 flex-1 overflow-y-auto">
          <div className="grid grid-cols-[2fr_2fr_1fr_2fr] border-b border-border bg-card text-xs font-medium">
            <div className="px-3 py-1.5">参数名</div>
            <div className="px-3 py-1.5">描述</div>
            <div className="px-3 py-1.5 text-right">实时值</div>
            <div className="px-3 py-1.5">操作</div>
          </div>
          {instanceTags.map((tag) => {
            const v = readValue(tag.name)
            const force = forces[tag.name]
            const quality = qualities[tag.name]
            const showForce = !!force && force.mode !== 'follow'
            return (
              <div key={tag.name} className="grid grid-cols-[2fr_2fr_1fr_2fr] border-b border-border/50 text-xs" data-testid={`runtime-detail-row-${tag.name}`}>
                <div className="truncate px-3 py-1.5 font-mono">{tag.attribute || tag.name}</div>
                <div className="truncate px-3 py-1.5 text-muted-foreground">{tag.description}</div>
                <div className="px-3 py-1.5 text-right font-mono">
                  {typeof v === 'number' ? v.toFixed(4) : '—'}
                </div>
                <div className="px-3 py-1.5">
                  <div className="flex flex-col gap-1">
                    {showForce ? (
                      <div className="text-xs">
                        固定输出：{typeof force?.value === 'number' ? force.value.toFixed(4) : '—'}
                        {isConnected && hasRuntimeName ? (
                          <button
                            type="button"
                            onClick={() => void handleClear(tag.name, 'fix')}
                            className="ml-2 rounded border border-border px-1 text-xs hover:bg-secondary"
                            data-testid={`runtime-detail-clear-fix-${tag.name}`}
                          >
                            解除
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                    {quality ? (
                      <div className="text-xs">
                        质量码：{quality}
                        {isConnected && hasRuntimeName ? (
                          <button
                            type="button"
                            onClick={() => void handleClear(tag.name, 'quality')}
                            className="ml-2 rounded border border-border px-1 text-xs hover:bg-secondary"
                            data-testid={`runtime-detail-clear-quality-${tag.name}`}
                          >
                            解除
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                    {isConnected && hasRuntimeName && tag.writable ? (
                      <select
                        value=""
                        onChange={(e) => {
                          const v = e.target.value as OpKind
                          if (!v) return
                          setOpKind(v)
                          setOpTargetTag(tag.name)
                          setInputValue(v === 'sv' ? '0' : '0')
                          setError(null)
                        }}
                        className="rounded border border-border bg-background px-2 py-0.5 text-xs"
                        data-testid={`runtime-detail-action-${tag.name}`}
                      >
                        <option value="">选择操作</option>
                        <option value="fix">固定 UA 输出值</option>
                        <option value="sv">设置设定值</option>
                        <option value="quality">修改 UA 质量码</option>
                      </select>
                    ) : null}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {opKind ? (
        <div className="mt-2 rounded-md border border-border bg-card p-3" data-testid="runtime-detail-op-dialog">
          <div className="mb-2 text-xs font-medium">
            {opKind === 'fix' && `固定 UA 输出：${opTargetTag}`}
            {opKind === 'sv' && `设置设定值：${opTargetTag}`}
            {opKind === 'quality' && `修改 UA 质量码：${opTargetTag}`}
          </div>
          {opKind === 'quality' ? (
            <select
              value={qualityValue}
              onChange={(e) => setQualityValue(e.target.value as 'Good' | 'Uncertain' | 'Bad')}
              className="block w-full rounded-md border border-border bg-background px-2 py-1 text-sm"
              data-testid="runtime-detail-op-quality"
            >
              <option value="Good">Good</option>
              <option value="Uncertain">Uncertain</option>
              <option value="Bad">Bad</option>
            </select>
          ) : (
            <input
              type="number"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              className="block w-full rounded-md border border-border bg-background px-2 py-1 text-sm"
              data-testid="runtime-detail-op-input"
            />
          )}
          {error ? (
            <div className="mt-2 text-xs text-destructive" data-testid="runtime-detail-op-error">
              {error}
            </div>
          ) : null}
          <div className="mt-3 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setOpKind('')
                setOpTargetTag(null)
                setError(null)
              }}
              className="rounded-md border border-border px-3 py-1 text-xs hover:bg-secondary"
              data-testid="runtime-detail-op-cancel"
            >
              取消
            </button>
            <button
              type="button"
              onClick={() => void handleApply()}
              className="rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground"
              data-testid="runtime-detail-op-confirm"
            >
              确认
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}