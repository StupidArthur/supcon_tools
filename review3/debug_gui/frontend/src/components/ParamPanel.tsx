import { useState, useMemo } from 'react'
import { useStore } from '../store/useStore'
import type { ProgramItem } from '../types'

// 已知的算法类型 -> input_schema 映射（从 review3 components/programs 提取）
// connectable=false 的参数是可调参数（PB/TI/TD 等）
// connectable=true 的参数是输入引脚（PV/SV 等，由表达式传入）
const KNOWN_INPUT_SCHEMAS: Record<string, Array<{ name: string; connectable: boolean; desc: string }>> = {
  PID: [
    { name: 'PB', connectable: false, desc: '比例带' },
    { name: 'TI', connectable: false, desc: '积分时间(秒)' },
    { name: 'TD', connectable: false, desc: '微分时间(秒)' },
    { name: 'SV', connectable: true, desc: '设定值' },
    { name: 'PV', connectable: true, desc: '过程变量' },
    { name: 'H', connectable: false, desc: '输出上限' },
    { name: 'L', connectable: false, desc: '输出下限' },
    { name: 'MODE', connectable: false, desc: '运行模式(1=运算)' },
  ],
  CYLINDRICAL_TANK: [
    { name: 'height', connectable: false, desc: '水箱高度(m)' },
    { name: 'radius', connectable: false, desc: '水箱半径(m)' },
    { name: 'outlet_area', connectable: false, desc: '出水口面积(m²)' },
  ],
  VALVE: [
    { name: 'full_travel_time', connectable: false, desc: '满行程时间(s)' },
  ],
  SINE_WAVE: [
    { name: 'amplitude', connectable: false, desc: '幅值' },
    { name: 'frequency', connectable: false, desc: '频率(Hz)' },
    { name: 'phase', connectable: false, desc: '相位(rad)' },
    { name: 'offset', connectable: false, desc: '直流偏置' },
  ],
}

// 算法类型的 stored_attributes（只读输出属性）
const KNOWN_STORED_ATTRS: Record<string, string[]> = {
  PID: ['MV', 'PV', 'SV', 'PB', 'TI', 'TD', 'H', 'L', 'MODE'],
  CYLINDRICAL_TANK: ['level'],
  VALVE: ['current_opening', 'target_opening', 'outlet_flow'],
  SINE_WAVE: ['out'],
}

function getInputSchema(item: ProgramItem) {
  const typeKey = item.type.toUpperCase()
  return KNOWN_INPUT_SCHEMAS[typeKey] || []
}

function getStoredAttrs(item: ProgramItem) {
  const typeKey = item.type.toUpperCase()
  return KNOWN_STORED_ATTRS[typeKey] || []
}

/** 判断属性是否可调（init_args 类参数） */
function isEditableAttr(item: ProgramItem, attrName: string): boolean {
  const schema = getInputSchema(item)
  const found = schema.find((s) => s.name === attrName)
  if (found) return !found.connectable
  // 不在 input_schema 里的 stored_attributes（如 MV）是只读输出
  return false
}

/** 判断属性是否只读输出（算法计算结果） */
function isOutputAttr(item: ProgramItem, attrName: string): boolean {
  const schema = getInputSchema(item)
  const inSchema = schema.some((s) => s.name === attrName)
  if (inSchema) return false
  const stored = getStoredAttrs(item)
  return stored.includes(attrName)
}

export function ParamPanel() {
  const yamlConfig = useStore((s) => s.yamlConfig)
  const batchResult = useStore((s) => s.batchResult)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

  // 从批量结果中提取最新值（用于只读显示）
  const latestValues = useMemo(() => {
    if (!batchResult || batchResult.rows.length === 0) return {}
    return batchResult.rows[batchResult.rows.length - 1]
  }, [batchResult])

  if (!yamlConfig) {
    return (
      <div className="w-72 border-r border-border bg-card p-4">
        <div className="text-xs text-muted-foreground">请先选择 YAML 配置文件</div>
      </div>
    )
  }

  const toggleCollapse = (name: string) => {
    setCollapsed((prev) => ({ ...prev, [name]: !prev[name] }))
  }

  return (
    <div className="w-72 overflow-y-auto border-r border-border bg-card">
      <div className="space-y-2 p-2">
        {yamlConfig.program.map((item) => {
          const isCollapsed = collapsed[item.name] ?? false
          const isVariable = item.type.toUpperCase() === 'VARIABLE'

          return (
            <div key={item.name} className="rounded-md border border-border">
              {/* 标题栏 */}
              <button
                onClick={() => toggleCollapse(item.name)}
                className="flex w-full items-center justify-between px-2 py-1.5 text-xs font-medium hover:bg-secondary"
              >
                <span>{item.name}</span>
                <span className="flex items-center gap-1">
                  <span className="text-muted-foreground">{item.type}</span>
                  <span className="text-muted-foreground">{isCollapsed ? '▶' : '▼'}</span>
                </span>
              </button>

              {/* 参数表单 */}
              {!isCollapsed && (
                <div className="space-y-1 border-t border-border p-2">
                  {isVariable ? (
                    <VariableParamEditor
                      name={item.name}
                      expression={item.expression}
                      latestValue={latestValues[item.name]}
                    />
                  ) : (
                    <InstanceParamEditor
                      item={item}
                      latestValues={latestValues}
                    />
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** VARIABLE 类型的参数编辑器 */
function VariableParamEditor({
  name, expression, latestValue,
}: {
  name: string
  expression: string
  latestValue: any
}) {
  return (
    <div className="space-y-1">
      <div className="text-xs text-muted-foreground">{expression}</div>
      <div className="flex items-center justify-between gap-2">
        <label className="text-xs text-muted-foreground">当前值</label>
        <span className="text-xs font-mono">
          {latestValue !== undefined ? Number(latestValue).toFixed(4) : '—'}
        </span>
      </div>
    </div>
  )
}

/** 算法/模型实例的参数编辑器 */
function InstanceParamEditor({
  item, latestValues,
}: {
  item: ProgramItem
  latestValues: Record<string, any>
}) {
  const schema = getInputSchema(item)
  const stored = getStoredAttrs(item)

  // 合并 init_args 中的值 + schema 中的描述
  const editableParams = schema.filter((s) => !s.connectable)
  const inputParams = schema.filter((s) => s.connectable)
  const outputParams = stored.filter((attr) => isOutputAttr(item, attr))

  return (
    <div className="space-y-2">
      {/* 可调参数（init_args 类） */}
      {editableParams.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs font-medium text-muted-foreground">可调参数</div>
          {editableParams.map((param) => {
            const value = item.initArgs?.[param.name]
            const latestKey = `${item.name}.${param.name}`
            const latest = latestValues[latestKey]
            return (
              <div key={param.name} className="flex items-center justify-between gap-2">
                <label className="text-xs text-muted-foreground" title={param.desc}>
                  {param.name}
                </label>
                <input
                  type="text"
                  defaultValue={value !== undefined ? String(value) : ''}
                  className="w-20 rounded border border-border bg-background px-1 py-0.5 text-xs font-mono"
                />
              </div>
            )
          })}
        </div>
      )}

      {/* 输入参数（connectable=true，由表达式传入） */}
      {inputParams.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs font-medium text-muted-foreground">输入</div>
          {inputParams.map((param) => {
            const latestKey = `${item.name}.${param.name}`
            const latest = latestValues[latestKey]
            return (
              <div key={param.name} className="flex items-center justify-between gap-2">
                <label className="text-xs text-muted-foreground" title={param.desc}>
                  {param.name}
                </label>
                <span className="text-xs font-mono text-muted-foreground">
                  {latest !== undefined ? Number(latest).toFixed(4) : '—'}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* 只读输出 */}
      {outputParams.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs font-medium text-muted-foreground">输出</div>
          {outputParams.map((attr) => {
            const latestKey = `${item.name}.${attr}`
            const latest = latestValues[latestKey]
            return (
              <div key={attr} className="flex items-center justify-between gap-2">
                <label className="text-xs text-muted-foreground">{attr}</label>
                <span className="text-xs font-mono text-muted-foreground">
                  {latest !== undefined ? Number(latest).toFixed(4) : '—'}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* 表达式 */}
      {item.expression && (
        <div className="pt-1 border-t border-border">
          <div className="text-xs text-muted-foreground/60 truncate" title={item.expression}>
            {item.expression}
          </div>
        </div>
      )}
    </div>
  )
}
