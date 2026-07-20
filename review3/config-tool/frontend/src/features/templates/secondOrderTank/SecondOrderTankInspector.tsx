import { useState } from 'react'
import { SECOND_ORDER_TANK_OBJECTS, FIELD_DISPLAY, LT_201_BINDING } from './definition'
import type { SelectedObjectId, DraftConfig, ValidationIssue } from '../types'
import { tankVolumeLiters } from './conversions'
import { useTemplateStore } from '../useTemplateStore'
import { useRuntimeStore } from '../../runtime/useRuntimeStore'
import {
  formatRuntimeNumber,
  isRuntimeRunning,
} from '../../runtime/dataSelection'
import type { ConnectionState, RuntimeSnapshot } from '../../runtime/types'

// 页签类型
type InspectorTab = 'config' | 'runtime' | 'trend'

interface InspectorProps {
  selectedObjectId: SelectedObjectId | null
  draft: DraftConfig
  dirtyPaths: Set<string>
  validationErrors: ValidationIssue[]
  validationWarnings: ValidationIssue[]
  onEditField: (path: string, value: number | string) => void
}

export function SecondOrderTankInspector({
  selectedObjectId,
  draft,
  dirtyPaths,
  validationErrors,
  validationWarnings,
  onEditField,
}: InspectorProps) {
  const [activeTab, setActiveTab] = useState<InspectorTab>('config')

  const selectedMeta = SECOND_ORDER_TANK_OBJECTS.find((o) => o.id === selectedObjectId)

  // 未选中对象时显示模板说明
  if (!selectedMeta) {
    return (
      <div className="flex h-full flex-col" data-testid="inspector-empty">
        <div className="border-b border-border p-3">
          <div className="text-sm font-medium">单阀门二阶水箱</div>
          <div className="text-xs text-muted-foreground">模板说明</div>
        </div>
        <div className="flex-1 overflow-y-auto p-3 text-xs text-muted-foreground space-y-3">
          <p>
            本模板展示一个由 PID 控制的二阶水箱系统。
            水源通过调节阀向上游水箱供水，再流入下游水箱。
            PID 控制器通过测量下游水箱液位来调节阀门开度，维持液位在设定值。
          </p>
          <div className="rounded-md bg-secondary/50 p-2 space-y-1">
            <div className="font-medium text-foreground">默认工况</div>
            <div>水源流量：{(draft.sourceFlow * 60_000).toFixed(1)} L/min</div>
            <div>Tank 1 初始液位：{draft.tank1.initialLevel.toFixed(3)} m</div>
            <div>Tank 2 初始液位：{draft.tank2.initialLevel.toFixed(3)} m</div>
            <div>PID SV：{draft.pid.SV.toFixed(3)} m</div>
          </div>
          <p>点击左侧流程图中的对象查看和编辑参数。</p>
          {(validationErrors.length > 0 || validationWarnings.length > 0) && (
            <div className="space-y-1 pt-2 border-t border-border">
              {validationErrors.map((e) => (
                <div key={`e-${e.path}`} className="text-destructive">
                  {e.message}
                </div>
              ))}
              {validationWarnings.map((w) => (
                <div key={`w-${w.path}`} className="text-amber-600">
                  {w.message}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }

  // 获取当前对象的字段列表
  const objectFields = FIELD_DISPLAY.filter(
    (f) => f.appliesTo === selectedMeta.id || f.appliesTo === 'all'
  )

  // 计算派生值
  const derivedValues: Record<string, number> = {}
  if (selectedMeta.id === 'tank_1') {
    derivedValues['tank1.volume'] = tankVolumeLiters(draft.tank1.height, draft.tank1.radius)
  } else if (selectedMeta.id === 'tank_2') {
    derivedValues['tank2.volume'] = tankVolumeLiters(draft.tank2.height, draft.tank2.radius)
  }

  return (
    <div className="flex h-full flex-col" data-testid="inspector">
      {/* 标题区 */}
      <div className="border-b border-border p-3">
        <div className="text-sm font-medium">{selectedMeta.displayName}</div>
        <div className="text-xs text-muted-foreground">
          {selectedMeta.id} · {selectedMeta.componentType}
        </div>
      </div>

      {/* 页签切换 */}
      <div className="flex border-b border-border">
        {(['config', 'runtime', 'trend'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex-1 py-2 text-xs font-medium transition-colors ${
              activeTab === tab
                ? 'border-b-2 border-primary text-primary'
                : 'text-muted-foreground hover:text-foreground'
            }`}
            data-testid={`tab-${tab}`}
          >
            {tab === 'config' ? '组态' : tab === 'runtime' ? '运行' : '趋势'}
          </button>
        ))}
      </div>

      {/* 页签内容 */}
      <div className="flex-1 overflow-y-auto p-3">
        {activeTab === 'config' && (selectedMeta.id === 'lt_201' ? (
          <LTConfigTab />
        ) : (
          <ConfigTab
            fields={objectFields}
            draft={draft}
            dirtyPaths={dirtyPaths}
            validationErrors={validationErrors}
            validationWarnings={validationWarnings}
            advancedPrefixes={selectedMeta.advancedFieldPrefixes}
            derivedValues={derivedValues}
            onEditField={onEditField}
          />
        ))}
        {activeTab === 'runtime' && <RuntimeTab objectId={selectedMeta.id} />}
        {activeTab === 'trend' && <TrendTab objectId={selectedMeta.id} trendTags={selectedMeta.trendTags} />}
      </div>
    </div>
  )
}

function LTConfigTab() {
  return (
    <div className="text-xs space-y-3" data-testid="config-tab">
      <div className="rounded-md bg-secondary/50 p-2 space-y-2">
        <div className="font-medium text-foreground">信号绑定</div>
        <div><span className="text-muted-foreground">来源：</span> <span className="font-mono">{LT_201_BINDING.sourceTag}</span></div>
        <div><span className="text-muted-foreground">目标：</span> <span className="font-mono">{LT_201_BINDING.targetTag}</span></div>
      </div>
      <p className="text-muted-foreground">{LT_201_BINDING.description}</p>
      <div className="pt-2 border-t border-border text-muted-foreground">
        LT-201 是虚拟仪表，不包含可编辑参数。
      </div>
    </div>
  )
}

// 组态页签
function ConfigTab({
  fields,
  draft,
  dirtyPaths,
  validationErrors,
  validationWarnings,
  advancedPrefixes,
  derivedValues,
  onEditField,
}: {
  fields: typeof FIELD_DISPLAY
  draft: DraftConfig
  dirtyPaths: Set<string>
  validationErrors: ValidationIssue[]
  validationWarnings: ValidationIssue[]
  advancedPrefixes: string[]
  derivedValues: Record<string, number>
  onEditField: (path: string, value: number | string) => void
}) {
  const [showAdvanced, setShowAdvanced] = useState(false)

  const basicFields = fields.filter(
    (f) => !advancedPrefixes.some((p) => f.path.startsWith(p))
  )
  const advancedFields = fields.filter((f) =>
    advancedPrefixes.some((p) => f.path.startsWith(p))
  )

  return (
    <div className="space-y-3" data-testid="config-tab">
      {/* 基础字段 */}
      {basicFields.map((field) => {
        // 派生只读值
        if (field.readOnly) {
          const derivedValue = derivedValues[field.path]
          if (derivedValue !== undefined) {
            return (
              <DerivedFieldDisplay
                key={field.path}
                field={field}
                value={derivedValue}
              />
            )
          }
          return null
        }

        return (
          <FieldEditor
            key={field.path}
            field={field}
            value={readField(draft, field.path)}
            isDirty={dirtyPaths.has(field.path)}
            error={validationErrors.find((e) => e.path === field.path)?.message}
            warning={validationWarnings.find((w) => w.path === field.path)?.message}
            rangeText={typeof field.range === 'function' ? field.range(draft) : field.range}
            onChange={(v) => onEditField(field.path, v)}
          />
        )
      })}

      {/* 高级字段折叠 */}
      {advancedFields.length > 0 && (
        <div className="pt-2 border-t border-border">
          <button
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex w-full items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            data-testid="toggle-advanced"
          >
            <span className={`transition-transform ${showAdvanced ? 'rotate-90' : ''}`}>
              ▶
            </span>
            高级参数 ({advancedFields.length})
          </button>
          {showAdvanced && (
            <div className="mt-2 space-y-3">
              {advancedFields.map((field) => (
                <FieldEditor
                  key={field.path}
                  field={field}
                  value={readField(draft, field.path)}
                  isDirty={dirtyPaths.has(field.path)}
                  error={validationErrors.find((e) => e.path === field.path)?.message}
                  warning={validationWarnings.find((w) => w.path === field.path)?.message}
                  rangeText={typeof field.range === 'function' ? field.range(draft) : field.range}
                  onChange={(v) => onEditField(field.path, v)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// 运行页签 - 阶段 4 显示真实 snapshot 数据。
// 关键：现场字段直接通过 useRuntimeStore selector 订阅，template store 不复制 runtime 状态。
// 严禁在 render 中通过 getState() 读取值冒充订阅。
// 这样 snapshot/connectionState/stale 变化时组件会自动重新渲染。
function RuntimeTab({ objectId }: { objectId: SelectedObjectId }) {
  // 显式订阅每个用到的 runtime 字段；这样 snapshot 更新会触发组件重新渲染。
  const runtimeState = useTemplateStore((s) => s.runtimeState)
  const snapshot = useRuntimeStore((s) => s.latestSnapshot)
  const connectionState = useRuntimeStore((s) => s.connectionState)
  const stale = useRuntimeStore((s) => s.stale)
  const runtimeName = useRuntimeStore((s) => s.runtimeName)
  const cycleTime = useRuntimeStore((s) => s.cycleTime)
  const snapshotReceivedAt = useRuntimeStore((s) => s.snapshotReceivedAt)

  const running = isRuntimeRunning(runtimeState)
  if (!running) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground" data-testid="runtime-tab">
        <div className="text-4xl mb-2">⏸</div>
        <div className="text-sm font-medium">未运行</div>
        <div className="text-xs mt-1">启动仿真后显示实时值</div>
      </div>
    )
  }

  const connLabel: Record<ConnectionState, string> = {
    idle: '空闲',
    connecting: '连接中',
    connected: stale ? '数据已过期' : '已连接',
    disconnected: '已断开',
    error: '错误',
  }

  const updatedAt =
    snapshotReceivedAt !== null ? new Date(snapshotReceivedAt) : null
  const updatedText = updatedAt
    ? `${updatedAt.toLocaleTimeString()}`
    : '—'

  const tags = runtimeTagsFor(objectId)
  return (
    <div className="space-y-3" data-testid="runtime-tab">
      {/* 连接状态 */}
      <div className="rounded-md bg-secondary/50 p-2 text-xs space-y-1">
        <div className="flex justify-between">
          <span className="text-muted-foreground">runtime</span>
          <span className="font-mono" data-testid="runtime-name">
            {runtimeName ?? '—'}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">连接</span>
          <span data-testid="runtime-connection">{connLabel[connectionState]}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">stale</span>
          <span data-testid="runtime-stale" className={stale ? 'text-red-600' : ''}>
            {stale ? '是' : '否'}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">更新时间</span>
          <span data-testid="runtime-updated-at" className="font-mono">
            {updatedText}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">cycleTime</span>
          <span className="font-mono">{cycleTime.toFixed(2)} s</span>
        </div>
      </div>

      {/* 字段位号 */}
      <div className="text-xs text-muted-foreground">实时位号</div>
      <div className="space-y-1.5">
        {tags.map((tag) => {
          const value = snapshot ? readRuntimeTag(snapshot, tag.tag) : null
          const present = value !== null
          return (
            <div
              key={tag.tag}
              className="flex items-center justify-between rounded-md bg-secondary/50 px-2 py-1.5 text-xs"
              data-testid={`runtime-field-${tag.tag}`}
            >
              <span className="font-mono text-muted-foreground">{tag.tag}</span>
              <span
                className={present ? 'font-mono' : 'font-mono text-red-500'}
              >
                {present ? formatRuntimeNumber(value, tag.digits, tag.unit) : '— 缺字段'}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// 每个对象的实时位号列表 + 显示精度
function runtimeTagsFor(id: SelectedObjectId): { tag: string; digits: number; unit: string }[] {
  switch (id) {
    case 'source_flow':
      return [{ tag: 'source_flow', digits: 5, unit: 'm³/s' }]
    case 'valve_1':
      return [
        { tag: 'valve_1.target_opening', digits: 1, unit: '%' },
        { tag: 'valve_1.current_opening', digits: 1, unit: '%' },
        { tag: 'valve_1.inlet_flow', digits: 5, unit: 'm³/s' },
        { tag: 'valve_1.outlet_flow', digits: 5, unit: 'm³/s' },
      ]
    case 'tank_1':
      return [
        { tag: 'tank_1.level', digits: 3, unit: 'm' },
        { tag: 'tank_1.inlet_flow', digits: 5, unit: 'm³/s' },
        { tag: 'tank_1.outlet_flow', digits: 5, unit: 'm³/s' },
      ]
    case 'tank_2':
      return [
        { tag: 'tank_2.level', digits: 3, unit: 'm' },
        { tag: 'tank_2.inlet_flow', digits: 5, unit: 'm³/s' },
        { tag: 'tank_2.outlet_flow', digits: 5, unit: 'm³/s' },
      ]
    case 'pid2':
      return [
        { tag: 'pid2.PV', digits: 3, unit: 'm' },
        { tag: 'pid2.SV', digits: 3, unit: 'm' },
        { tag: 'pid2.CSV', digits: 3, unit: 'm' },
        { tag: 'pid2.MV', digits: 1, unit: '%' },
        { tag: 'pid2.PB', digits: 1, unit: '' },
        { tag: 'pid2.TI', digits: 1, unit: 's' },
        { tag: 'pid2.TD', digits: 1, unit: 's' },
        { tag: 'pid2.KD', digits: 1, unit: '' },
        { tag: 'pid2.MODE', digits: 0, unit: '' },
        { tag: 'pid2.SWPN', digits: 0, unit: '' },
      ]
    case 'lt_201':
      return [
        { tag: LT_201_BINDING.sourceTag, digits: 3, unit: 'm' },
        { tag: LT_201_BINDING.targetTag, digits: 3, unit: 'm' },
      ]
    default:
      return []
  }
}

// readRuntimeTag: 从 RuntimeSnapshot 读字段；缺失返回 null（绝不返回 0/NaN 假装有值）。
function readRuntimeTag(snap: RuntimeSnapshot, tag: string): number | null {
  const fn = (v: number | undefined): number | null =>
    Number.isFinite(v) ? (v as number) : null
  switch (tag) {
    case 'source_flow':
      return fn(snap.sourceFlow)
    case 'valve_1.target_opening':
      return fn(snap.valve.targetOpening)
    case 'valve_1.current_opening':
      return fn(snap.valve.currentOpening)
    case 'valve_1.inlet_flow':
      return fn(snap.valve.inletFlow)
    case 'valve_1.outlet_flow':
      return fn(snap.valve.outletFlow)
    case 'tank_1.level':
      return fn(snap.tank1.level)
    case 'tank_1.inlet_flow':
      return fn(snap.tank1.inletFlow)
    case 'tank_1.outlet_flow':
      return fn(snap.tank1.outletFlow)
    case 'tank_2.level':
      return fn(snap.tank2.level)
    case 'tank_2.inlet_flow':
      return fn(snap.tank2.inletFlow)
    case 'tank_2.outlet_flow':
      return fn(snap.tank2.outletFlow)
    case 'pid2.PV':
      return fn(snap.pid.PV)
    case 'pid2.SV':
      return fn(snap.pid.SV)
    case 'pid2.CSV':
      return fn(snap.pid.CSV)
    case 'pid2.MV':
      return fn(snap.pid.MV)
    case 'pid2.PB':
      return fn(snap.pid.PB)
    case 'pid2.TI':
      return fn(snap.pid.TI)
    case 'pid2.TD':
      return fn(snap.pid.TD)
    case 'pid2.KD':
      return fn(snap.pid.KD)
    case 'pid2.MODE':
      return fn(snap.pid.MODE)
    case 'pid2.SWPN':
      return fn(snap.pid.SWPN)
    default:
      return null
  }
}

// 趋势页签
function TrendTab({ objectId, trendTags }: { objectId: SelectedObjectId; trendTags: string[] }) {
  return (
    <div className="space-y-3" data-testid="trend-tab">
      <div className="text-xs text-muted-foreground">
        推荐将以下位号添加到趋势图：
      </div>
      <div className="space-y-1.5">
        {trendTags.map((tag) => (
          <div
            key={tag}
            className="flex items-center gap-2 rounded-md bg-secondary/50 px-2 py-1.5 text-xs"
          >
            <span className="h-2 w-2 rounded-full bg-primary" />
            <span className="font-mono">{tag}</span>
          </div>
        ))}
      </div>
      <div className="text-[10px] text-muted-foreground pt-2 border-t border-border">
        趋势功能将在阶段 6 实现
      </div>
    </div>
  )
}

// 派生只读字段显示
function DerivedFieldDisplay({
  field,
  value,
}: {
  field: (typeof FIELD_DISPLAY)[number]
  value: number
}) {
  return (
    <div className="space-y-1" data-testid={`field-${field.path}`}>
      <div className="flex items-center justify-between">
        <label className="text-xs text-muted-foreground">
          {field.label}
          {field.displayUnit && field.displayUnit !== '—' && (
            <span className="ml-1 text-[10px]">({field.displayUnit})</span>
          )}
        </label>
        <span className="text-[10px] text-muted-foreground/60">只读</span>
      </div>
      <div className="rounded-md border border-border bg-secondary/50 px-2 py-1.5 text-xs">
        {formatDisplayValue(value, field)}
      </div>
      {field.helpText && (
        <div className="text-[10px] text-muted-foreground/80">{field.helpText}</div>
      )}
    </div>
  )
}

// 字段编辑器组件
function FieldEditor({
  field,
  value,
  isDirty,
  error,
  warning,
  rangeText,
  onChange,
}: {
  field: (typeof FIELD_DISPLAY)[number]
  value: number
  isDirty: boolean
  error?: string
  warning?: string
  rangeText?: string
  onChange: (value: number) => void
}) {
  const [inputValue, setInputValue] = useState<string | null>(null)
  const [isEditing, setIsEditing] = useState(false)

  // 转换为显示值
  const displayValue = field.toDisplay ? field.toDisplay(value) : value
  const formattedValue = inputValue ?? formatDisplayValue(displayValue, field)
  const hasIssue = !!error || !!warning

  const handleFocus = () => {
    setInputValue(formatDisplayValue(displayValue, field))
    setIsEditing(true)
  }

  const handleBlur = () => {
    if (inputValue !== null) {
      const parsed = Number(inputValue.trim())
      if (Number.isFinite(parsed)) {
        // 转换回原始值
        const rawValue = field.fromDisplay ? field.fromDisplay(parsed) : parsed
        onChange(rawValue)
      }
    }
    setInputValue(null)
    setIsEditing(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleBlur()
    } else if (e.key === 'Escape') {
      setInputValue(null)
      setIsEditing(false)
    }
  }

  return (
    <div className="space-y-1" data-testid={`field-${field.path}`}>
      <div className="flex items-center justify-between">
        <label className="text-xs text-muted-foreground">
          {field.label}
          {field.displayUnit && field.displayUnit !== '—' && (
            <span className="ml-1 text-[10px]">({field.displayUnit})</span>
          )}
        </label>
        <div className="flex items-center gap-1">
          {isDirty && (
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500" title="已修改" />
          )}
          <span className="text-[10px] text-muted-foreground/60">
            {field.effectiveOn === 'restart' ? '重启生效' : '实时生效'}
          </span>
        </div>
      </div>
      <input
        type="text"
        value={formattedValue}
        onChange={(e) => setInputValue(e.target.value)}
        onFocus={handleFocus}
        onBlur={handleBlur}
        onKeyDown={handleKeyDown}
        className={`w-full rounded-md border px-2 py-1.5 text-xs transition-colors ${
          isEditing
            ? 'border-primary bg-background'
            : hasIssue
              ? error
                ? 'border-destructive bg-destructive/5'
                : 'border-amber-500 bg-amber-50'
              : 'border-border bg-secondary/50'
        } focus:outline-none focus:ring-1 focus:ring-primary`}
        data-testid={`input-${field.path}`}
      />
      {/* YAML 参数名 */}
      {field.yamlPath && (
        <div className="text-[9px] font-mono text-muted-foreground/60">
          {field.yamlPath}
        </div>
      )}
      {/* 合法范围 */}
      {rangeText && (
        <div className="text-[9px] text-muted-foreground/60">
          范围：{rangeText} {field.displayUnit}
        </div>
      )}
      {error && (
        <div className="text-[10px] text-destructive" data-testid={`error-${field.path}`}>
          {error}
        </div>
      )}
      {warning && !error && (
        <div className="text-[10px] text-amber-600" data-testid={`warning-${field.path}`}>
          {warning}
        </div>
      )}
      {field.helpText && !error && !warning && (
        <div className="text-[10px] text-muted-foreground/80">{field.helpText}</div>
      )}
    </div>
  )
}

// 读取 draft 中的字段值
function readField(draft: DraftConfig, path: string): number {
  const segs = path.split('.')
  let cur: any = draft
  for (const s of segs) {
    if (cur == null) return NaN
    cur = cur[s]
  }
  return typeof cur === 'number' ? cur : NaN
}

// 格式化显示值
function formatDisplayValue(value: number, field: (typeof FIELD_DISPLAY)[number]): string {
  if (isNaN(value)) return '—'
  // 根据单位选择精度
  if (field.displayUnit === 'mm') {
    return value.toFixed(2)
  }
  if (field.displayUnit === 'L/min') {
    return value.toFixed(1)
  }
  if (field.displayUnit === 'L') {
    return value.toFixed(1)
  }
  if (field.displayUnit === 'm') {
    return value.toFixed(3)
  }
  if (field.displayUnit === '%') {
    return value.toFixed(1)
  }
  if (field.displayUnit === 's') {
    return value.toFixed(2)
  }
  return value.toFixed(3)
}
