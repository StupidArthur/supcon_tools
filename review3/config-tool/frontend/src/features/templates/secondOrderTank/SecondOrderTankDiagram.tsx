import type { SelectedObjectId, DraftConfig } from '../types'
import { useTemplateStore } from '../useTemplateStore'
import { useRuntimeStore } from '../../runtime/useRuntimeStore'
import {
  selectTankLevel,
  selectValveOpening,
  selectValveTargetOpening,
  selectSourceFlow,
  selectPIDSetpoint,
  selectPIDMode,
  selectPipeFlow,
  shouldShowFlowAnimation,
  formatRuntimeNumber,
} from '../../runtime/dataSelection'

// 固定 P&ID 布局常量
const LAYOUT = {
  // 画布尺寸
  width: 900,
  height: 500,
  // 水源
  source: { x: 80, y: 200 },
  // 阀门
  valve: { x: 250, y: 200 },
  // Tank 1
  tank1: { x: 420, y: 150, width: 100, height: 200 },
  // Tank 2
  tank2: { x: 650, y: 150, width: 100, height: 200 },
  // LT-201 液位测量
  lt: { x: 700, y: 400 },
  // LIC-201 PID 控制器
  pid: { x: 500, y: 400 },
  // 排水
  drain: { x: 700, y: 450 },
} as const

interface DiagramProps {
  draft: DraftConfig
  selectedObjectId: SelectedObjectId | null
  onSelect: (id: SelectedObjectId | null) => void
}

export function SecondOrderTankDiagram({ draft, selectedObjectId, onSelect }: DiagramProps) {
  // 阶段 4：runtime 数据通过 template store 透传（由 SecondOrderTankPage 同步写入）。
  const runtimeState = useTemplateStore((s) => s.runtimeState)
  const runningConfig = useTemplateStore((s) => s.runningConfig)

  // runtime 现场值只有一个来源，禁止经过 template store 复制后产生跨代延迟。
  const latestSnapshot = useRuntimeStore((s) => s.latestSnapshot)
  const connState = useRuntimeStore((s) => s.connectionState)
  const isStale = useRuntimeStore((s) => s.stale)

  // 阶段 4 决策点：
  //   - 停止/组态态：完全使用 draft（initialLevel / initialOpening）
  //   - 运行态：完全使用 latestSnapshot（真实 level / current_opening）
  //   严禁运行态用 draft 冒充实时值。
  const ctx = {
    runtimeState,
    latestSnapshot,
    draft,
    runningConfig,
  }

  // Tank 1 液位
  const tank1 = selectTankLevel(ctx, 'tank1')
  const tank1LevelRatio =
    tank1.ratio !== null ? Math.max(0, Math.min(1, tank1.ratio)) : 0
  const tank1OutOfRange = tank1.outOfRange
  const tank1LevelDisplay = tank1.level

  // Tank 2 液位
  const tank2 = selectTankLevel(ctx, 'tank2')
  const tank2LevelRatio =
    tank2.ratio !== null ? Math.max(0, Math.min(1, tank2.ratio)) : 0
  const tank2OutOfRange = tank2.outOfRange

  // SV 标线比例 - 仅在 Tank 2；运行态取 snapshot.pid.SV，停止态取 draft.pid.SV。
  // 缺失字段显示 `—` 和告警，绝不强行使用 draft 冒充实时值。
  const pidSvResult = selectPIDSetpoint(ctx)
  const pidSv = pidSvResult.value
  const svRatioRaw =
    pidSv !== null && tank2.height !== null && tank2.height > 0
      ? pidSv / tank2.height
      : null
  const svRatio = svRatioRaw !== null ? Math.max(0, Math.min(1, svRatioRaw)) : null
  const svOutOfRange = svRatioRaw !== null && (svRatioRaw < 0 || svRatioRaw > 1)
  const svMissing = !pidSvResult.present || !pidSvResult.finite

  // 阀门开度 - 必须 current_opening（运行态）或 initialOpening（停止态）
  const valveOpening = selectValveOpening(ctx)
  const valveTargetOpening = selectValveTargetOpening(ctx)

  // 水源流量 - 运行态取 snapshot.source_flow，停止态取 draft.sourceFlow。
  // 缺失字段显示 `—`，绝不在运行态回退到 draft 冒充实时值。
  const sourceFlowResult = selectSourceFlow(ctx)
  const sourceFlowM3s = sourceFlowResult.value
  const sourceFlowLpmDisplay =
    sourceFlowM3s !== null && Number.isFinite(sourceFlowM3s)
      ? sourceFlowM3s * 60_000
      : null

  // 流量 - 仅运行态有真实值；停止态为 null
  const inletFlow = selectPipeFlow(ctx, 'inlet')
  const valveOutletFlow = selectPipeFlow(ctx, 'valveToTank1')
  const tank1OutletFlow = selectPipeFlow(ctx, 'tank1ToTank2')
  const tank2OutletFlow = selectPipeFlow(ctx, 'tank2Drain')

  // 流动动画
  const inletFlowAnim = shouldShowFlowAnimation(ctx, connState, isStale, 'inlet')
  const valveToTank1FlowAnim = shouldShowFlowAnimation(ctx, connState, isStale, 'valveToTank1')
  const tank1ToTank2FlowAnim = shouldShowFlowAnimation(ctx, connState, isStale, 'tank1ToTank2')
  const tank2DrainFlowAnim = shouldShowFlowAnimation(ctx, connState, isStale, 'tank2Drain')

  // PID MODE - 运行态取 snapshot.pid.MODE，停止态取 draft.pid.MODE。
  // 缺失字段显示 `M?` 并告警；不允许在运行态用 draft 冒充实时 MODE。
  const pidModeResult = selectPIDMode(ctx)
  const pidMode = pidModeResult.value
  const modeLabel =
    pidMode === null
      ? 'M?'
      : pidMode === 5
        ? 'AUTO'
        : pidMode === 4
          ? 'MAN'
          : `M${pidMode}`

  const isRunning = runtimeState === 'SIMULATION_RUNNING' || runtimeState === 'REALTIME_RUNNING'

  return (
    <svg
      viewBox={`0 0 ${LAYOUT.width} ${LAYOUT.height}`}
      className="h-full w-full"
      data-testid="pid-diagram"
    >
      {/* 背景 */}
      <rect width={LAYOUT.width} height={LAYOUT.height} fill="var(--background)" />

      {/* 组态预览/实时模式标记 */}
      <text
        x={LAYOUT.width / 2}
        y={24}
        textAnchor="middle"
        className={`text-[11px] ${isRunning && !isStale ? 'fill-green-700' : isStale ? 'fill-red-700' : 'fill-muted-foreground'}`}
      >
        {!isRunning
          ? '当前为组态预览，不是实时值'
          : isStale
            ? '数据已过期（WebSocket 断开或长时间无 snapshot）'
            : `实时运行 · ${connState === 'connected' ? '已连接' : connState}`}
      </text>

      {/* 过程管线 - 入口 */}
      <ProcessPipe
        testId="pipe-inlet"
        points={[
          [LAYOUT.source.x + 40, LAYOUT.source.y],
          [LAYOUT.valve.x - 20, LAYOUT.valve.y],
        ]}
        hasFlow={inletFlowAnim}
      />

      {/* 过程管线 - 阀门到 Tank 1 */}
      <ProcessPipe
        testId="pipe-valve-to-tank1"
        points={[
          [LAYOUT.valve.x + 20, LAYOUT.valve.y],
          [LAYOUT.tank1.x, LAYOUT.valve.y],
          [LAYOUT.tank1.x, LAYOUT.tank1.y + 20],
        ]}
        hasFlow={valveToTank1FlowAnim}
      />

      {/* 过程管线 - Tank 1 到 Tank 2 */}
      <ProcessPipe
        testId="pipe-tank1-to-tank2"
        points={[
          [LAYOUT.tank1.x + LAYOUT.tank1.width, LAYOUT.tank1.y + LAYOUT.tank1.height - 30],
          [LAYOUT.tank1.x + LAYOUT.tank1.width + 40, LAYOUT.tank1.y + LAYOUT.tank1.height - 30],
          [LAYOUT.tank2.x - 40, LAYOUT.tank2.y + LAYOUT.tank2.height - 30],
          [LAYOUT.tank2.x, LAYOUT.tank2.y + LAYOUT.tank2.height - 30],
        ]}
        hasFlow={tank1ToTank2FlowAnim}
      />

      {/* 过程管线 - Tank 2 排水 */}
      <ProcessPipe
        testId="pipe-tank2-drain"
        points={[
          [LAYOUT.tank2.x + LAYOUT.tank2.width / 2, LAYOUT.tank2.y + LAYOUT.tank2.height],
          [LAYOUT.tank2.x + LAYOUT.tank2.width / 2, LAYOUT.drain.y],
        ]}
        hasFlow={tank2DrainFlowAnim}
      />

      {/* 控制信号 - PV（LT-201 到 PID） */}
      <ControlSignal
        points={[
          [LAYOUT.lt.x - 20, LAYOUT.lt.y],
          [LAYOUT.pid.x + 60, LAYOUT.pid.y - 10],
          [LAYOUT.pid.x + 20, LAYOUT.pid.y],
        ]}
        label="PV"
      />

      {/* 控制信号 - MV（PID 到阀门） */}
      <ControlSignal
        points={[
          [LAYOUT.pid.x - 20, LAYOUT.pid.y],
          [LAYOUT.valve.x, LAYOUT.pid.y - 10],
          [LAYOUT.valve.x, LAYOUT.valve.y + 30],
        ]}
        label="MV"
      />

      {/* 水源 */}
      <SourceSymbol
        x={LAYOUT.source.x}
        y={LAYOUT.source.y}
        selected={selectedObjectId === 'source_flow'}
        onClick={() => onSelect('source_flow')}
        flowLpm={sourceFlowLpmDisplay}
        present={sourceFlowResult.present}
        finite={sourceFlowResult.finite}
      />

      {/* 调节阀 */}
      <ValveSymbol
        x={LAYOUT.valve.x}
        y={LAYOUT.valve.y}
        selected={selectedObjectId === 'valve_1'}
        onClick={() => onSelect('valve_1')}
        opening={valveOpening.value}
        openingPresent={valveOpening.present}
        openingFinite={valveOpening.finite}
        targetOpening={valveTargetOpening.value}
        targetPresent={valveTargetOpening.present}
        targetFinite={valveTargetOpening.finite}
      />

      {/* Tank 1 */}
      <TankSymbol
        x={LAYOUT.tank1.x}
        y={LAYOUT.tank1.y}
        width={LAYOUT.tank1.width}
        height={LAYOUT.tank1.height}
        levelRatio={tank1LevelRatio}
        selected={selectedObjectId === 'tank_1'}
        onClick={() => onSelect('tank_1')}
        label="Tank 1"
        levelDisplay={tank1LevelDisplay}
        outOfRange={tank1OutOfRange}
      />

      {/* Tank 2 */}
      <TankSymbol
        x={LAYOUT.tank2.x}
        y={LAYOUT.tank2.y}
        width={LAYOUT.tank2.width}
        height={LAYOUT.tank2.height}
        levelRatio={tank2LevelRatio}
        selected={selectedObjectId === 'tank_2'}
        onClick={() => onSelect('tank_2')}
        label="Tank 2"
        levelDisplay={tank2.level}
        outOfRange={tank2OutOfRange}
        svRatio={svRatio}
        svOutOfRange={svOutOfRange}
        svValue={pidSv}
        svMissing={svMissing}
      />

      {/* LT-201 液位测量 */}
      <LTSymbol
        x={LAYOUT.lt.x}
        y={LAYOUT.lt.y}
        selected={selectedObjectId === 'lt_201'}
        onClick={() => onSelect('lt_201')}
      />

      {/* LIC-201 PID 控制器 */}
      <PIDSymbol
        x={LAYOUT.pid.x}
        y={LAYOUT.pid.y}
        selected={selectedObjectId === 'pid2'}
        onClick={() => onSelect('pid2')}
        sv={pidSv}
        mode={pidMode}
        modeLabel={modeLabel}
        svMissing={svMissing}
        modeMissing={pidMode === null}
      />

      {/* 排水标记 */}
      <DrainSymbol x={LAYOUT.drain.x} y={LAYOUT.drain.y} />

      {/* 流量数值（运行态 + 真实值） */}
      {isRunning && inletFlow !== null && (
        <text
          x={LAYOUT.source.x + 100}
          y={LAYOUT.source.y - 20}
          textAnchor="middle"
          className="fill-blue-600 text-[9px] font-mono"
          data-testid="inlet-flow-label"
        >
          {`入口 ${formatRuntimeNumber(inletFlow * 60_000, 2, 'L/min')}`}
        </text>
      )}
      {isRunning && valveOutletFlow !== null && (
        <text
          x={LAYOUT.valve.x + 60}
          y={LAYOUT.valve.y + 40}
          textAnchor="middle"
          className="fill-blue-600 text-[9px] font-mono"
          data-testid="valve-outlet-flow-label"
        >
          {`阀出口 ${formatRuntimeNumber(valveOutletFlow * 60_000, 2, 'L/min')}`}
        </text>
      )}
      {isRunning && tank1OutletFlow !== null && (
        <text x={575} y={300} textAnchor="middle" className="fill-blue-600 text-[9px] font-mono">
          {`Tank 1 出口 ${formatRuntimeNumber(tank1OutletFlow * 60_000, 2, 'L/min')}`}
        </text>
      )}
      {isRunning && tank2OutletFlow !== null && (
        <text x={755} y={425} textAnchor="start" className="fill-blue-600 text-[9px] font-mono">
          {`Tank 2 出口 ${formatRuntimeNumber(tank2OutletFlow * 60_000, 2, 'L/min')}`}
        </text>
      )}
    </svg>
  )
}

// 过程管线组件
function ProcessPipe({ points, hasFlow, testId }: { points: [number, number][]; hasFlow: boolean; testId: string }) {
  const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0]},${p[1]}`).join(' ')
  return (
    <path
      d={d}
      data-testid={testId}
      stroke={hasFlow ? 'var(--primary)' : 'var(--border)'}
      strokeWidth={3}
      fill="none"
      strokeDasharray={hasFlow ? '8 4' : undefined}
      className={hasFlow ? 'animate-flow' : undefined}
    />
  )
}

// 控制信号线组件（橙色虚线）
function ControlSignal({ points, label }: { points: [number, number][]; label: string }) {
  const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0]},${p[1]}`).join(' ')
  const midIdx = Math.floor(points.length / 2)
  const midX = (points[midIdx - 1][0] + points[midIdx][0]) / 2
  const midY = (points[midIdx - 1][1] + points[midIdx][1]) / 2 - 8

  return (
    <g>
      <path
        d={d}
        stroke="var(--orange-500, #f97316)"
        strokeWidth={2}
        fill="none"
        strokeDasharray="6 3"
      />
      <text x={midX} y={midY} textAnchor="middle" className="fill-orange-500 text-[10px] font-medium">
        {label}
      </text>
    </g>
  )
}

// 水源符号
function SourceSymbol({
  x, y, selected, onClick, flowLpm, present, finite,
}: {
  x: number; y: number; selected: boolean; onClick: () => void
  flowLpm: number | null
  present: boolean
  finite: boolean
}) {
  const displayValue =
    present && finite && flowLpm !== null && Number.isFinite(flowLpm)
      ? `${flowLpm.toFixed(1)} L/min`
      : '—'
  return (
    <g
      onClick={onClick}
      className="cursor-pointer"
      data-testid="source-flow"
      data-object-id="source_flow"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
    >
      {/* 水源圆圈 */}
      <circle
        cx={x}
        cy={y}
        r={20}
        fill="var(--blue-100, #dbeafe)"
        stroke={selected ? 'var(--primary)' : 'var(--blue-500, #3b82f6)'}
        strokeWidth={selected ? 3 : 2}
      />
      {/* 波浪线 */}
      <path
        d={`M${x - 10},${y} Q${x - 5},${y - 5} ${x},${y} Q${x + 5},${y + 5} ${x + 10},${y}`}
        stroke="var(--blue-500, #3b82f6)"
        strokeWidth={1.5}
        fill="none"
      />
      {/* 标签 */}
      <text x={x} y={y - 28} textAnchor="middle" className="fill-foreground text-[10px] font-medium">
        水源
      </text>
      <text
        x={x}
        y={y + 32}
        textAnchor="middle"
        data-testid="source-flow-value"
        className={`text-[9px] ${present && finite ? 'fill-muted-foreground' : 'fill-red-500'}`}
      >
        {displayValue}
      </text>
    </g>
  )
}

// 阀门符号
function ValveSymbol({
  x, y, selected, onClick, opening, openingPresent, openingFinite,
  targetOpening, targetPresent, targetFinite,
}: {
  x: number; y: number; selected: boolean; onClick: () => void
  opening: number | null
  openingPresent: boolean
  openingFinite: boolean
  targetOpening: number | null
  targetPresent: boolean
  targetFinite: boolean
}) {
  // 阀门开度指示器位置 - opening 缺失时显示警告
  const openingDisplay =
    openingPresent && openingFinite && opening !== null ? `${opening.toFixed(1)}%` : '—'
  const targetDisplay =
    targetPresent && targetFinite && targetOpening !== null
      ? `${targetOpening.toFixed(1)}%`
      : '—'
  const stemY = y - 15 - ((opening ?? 0) / 100) * 15

  return (
    <g
      onClick={onClick}
      className="cursor-pointer"
      data-testid="valve-1"
      data-object-id="valve_1"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
    >
      {/* 阀体（菱形） */}
      <polygon
        points={`${x},${y - 15} ${x + 20},${y} ${x},${y + 15} ${x - 20},${y}`}
        fill="var(--green-100, #dcfce7)"
        stroke={selected ? 'var(--primary)' : 'var(--green-600, #16a34a)'}
        strokeWidth={selected ? 3 : 2}
      />
      {/* 阀杆 */}
      <line
        x1={x}
        y1={y - 15}
        x2={x}
        y2={stemY}
        stroke="var(--green-600, #16a34a)"
        strokeWidth={2}
      />
      {/* 阀杆指示 */}
      <circle cx={x} cy={stemY} r={3} fill="var(--green-600, #16a34a)" />
      {/* 标签 */}
      <text x={x} y={y - 28} textAnchor="middle" className="fill-foreground text-[10px] font-medium">
        调节阀
      </text>
      <text
        x={x}
        y={y + 28}
        textAnchor="middle"
        className={`text-[9px] ${openingPresent && openingFinite ? 'fill-muted-foreground' : 'fill-red-500'}`}
        data-testid="valve-current-opening"
      >
        {openingDisplay}
      </text>
      <text
        x={x}
        y={y + 40}
        textAnchor="middle"
        className={`text-[9px] ${targetPresent && targetFinite ? 'fill-muted-foreground' : 'fill-red-500'}`}
        data-testid="valve-target-opening"
      >
        目标 {targetDisplay}
      </text>
      {!openingPresent && (
        <text x={x} y={y + 52} textAnchor="middle" className="fill-red-500 text-[8px]">
          缺字段
        </text>
      )}
    </g>
  )
}

// 水箱符号
function TankSymbol({
  x, y, width, height, levelRatio, selected, onClick, label, levelDisplay, outOfRange, svRatio, svOutOfRange, svValue, svMissing,
}: {
  x: number; y: number; width: number; height: number
  levelRatio: number; selected: boolean; onClick: () => void
  label: string
  levelDisplay: number | null
  outOfRange: boolean
  svRatio?: number | null; svOutOfRange?: boolean; svValue?: number | null; svMissing?: boolean
}) {
  const levelHeight = levelRatio * height
  const objectId = label === 'Tank 1' ? 'tank_1' : 'tank_2'

  // 真实数值显示：缺失或非有限 → `—`
  const levelText =
    levelDisplay !== null && Number.isFinite(levelDisplay)
      ? `${levelDisplay.toFixed(3)} m`
      : '—'

  return (
    <g
      onClick={onClick}
      className="cursor-pointer"
      data-testid={label.toLowerCase().replace(' ', '-')}
      data-object-id={objectId}
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
    >
      {/* 水箱外壳 */}
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        rx={4}
        fill="var(--card)"
        stroke={selected ? 'var(--primary)' : 'var(--border)'}
        strokeWidth={selected ? 3 : 2}
      />
      {/* 液位填充 */}
      <rect
        data-testid={`${objectId}-liquid`}
        x={x + 2}
        y={y + height - levelHeight}
        width={width - 4}
        height={levelHeight}
        fill="var(--blue-200, #bfdbfe)"
        opacity={0.7}
      />
      {/* SV 标线（仅 Tank 2） */}
      {svRatio !== undefined && svRatio !== null && svValue !== undefined && svValue !== null && !svMissing && (
        <g>
          <line
            data-testid="tank-2-sv-line"
            x1={x}
            y1={y + height - svRatio * height}
            x2={x + width}
            y2={y + height - svRatio * height}
            stroke={svOutOfRange ? 'var(--red-500, #ef4444)' : 'var(--red-500, #ef4444)'}
            strokeWidth={2}
            strokeDasharray="4 2"
          />
          <text
            x={x + width + 4}
            y={y + height - svRatio * height + 4}
            className="fill-red-500 text-[9px]"
          >
            SV
          </text>
          {/* 越界告警 */}
          {svOutOfRange && (
            <g>
              <circle cx={x + width + 24} cy={y - 12} r={8} fill="var(--red-500, #ef4444)" />
              <text x={x + width + 24} y={y - 8} textAnchor="middle" className="fill-white text-[10px] font-bold">
                !
              </text>
              <text x={x + width + 36} y={y - 8} className="fill-red-500 text-[9px]">
                SV 超出范围
              </text>
            </g>
          )}
        </g>
      )}
      {svMissing && (
        <text
          x={x + width / 2}
          y={y + height - 8}
          textAnchor="middle"
          className="fill-red-500 text-[8px]"
          data-testid="tank-2-sv-missing"
        >
          SV 缺字段
        </text>
      )}
      {/* 标签 */}
      <text x={x + width / 2} y={y - 8} textAnchor="middle" className="fill-foreground text-[10px] font-medium">
        {label}
      </text>
      <text
        x={x + width / 2}
        y={y + height + 16}
        textAnchor="middle"
        className={`text-[9px] ${levelDisplay !== null && Number.isFinite(levelDisplay) ? 'fill-muted-foreground' : 'fill-red-500'}`}
        data-testid={`${objectId}-level-text`}
      >
        {levelText}
      </text>
      {/* 越界告警（液位 > height 或 < 0） */}
      {outOfRange && (
        <text
          x={x + width / 2}
          y={y - 24}
          textAnchor="middle"
          className="fill-red-500 text-[8px]"
          data-testid={`${objectId}-out-of-range`}
        >
          液位越界
        </text>
      )}
    </g>
  )
}

// LT-201 液位测量符号
function LTSymbol({
  x, y, selected, onClick,
}: {
  x: number; y: number; selected: boolean; onClick: () => void
}) {
  return (
    <g
      onClick={onClick}
      className="cursor-pointer"
      data-testid="lt-201"
      data-object-id="lt_201"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
    >
      {/* 圆圈 */}
      <circle
        cx={x}
        cy={y}
        r={18}
        fill="var(--yellow-100, #fef9c3)"
        stroke={selected ? 'var(--primary)' : 'var(--yellow-600, #ca8a04)'}
        strokeWidth={selected ? 3 : 2}
      />
      {/* LT 文字 */}
      <text x={x} y={y - 4} textAnchor="middle" className="fill-yellow-700 text-[10px] font-bold">
        LT
      </text>
      <text x={x} y={y + 8} textAnchor="middle" className="fill-yellow-700 text-[8px]">
        201
      </text>
    </g>
  )
}

// PID 控制器符号
function PIDSymbol({
  x, y, selected, onClick, sv, mode, modeLabel, svMissing, modeMissing,
}: {
  x: number; y: number; selected: boolean; onClick: () => void
  sv: number | null
  mode: number | null
  modeLabel: string
  svMissing?: boolean
  modeMissing?: boolean
}) {
  return (
    <g
      onClick={onClick}
      className="cursor-pointer"
      data-testid="pid2"
      data-object-id="pid2"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
    >
      {/* 圆角矩形 */}
      <rect
        x={x - 40}
        y={y - 20}
        width={80}
        height={40}
        rx={6}
        fill="var(--purple-100, #f3e8ff)"
        stroke={selected ? 'var(--primary)' : 'var(--purple-600, #9333ea)'}
        strokeWidth={selected ? 3 : 2}
      />
      {/* LIC-201 */}
      <text x={x} y={y - 5} textAnchor="middle" className="fill-purple-700 text-[10px] font-bold">
        LIC-201
      </text>
      {/* PID */}
      <text x={x} y={y + 8} textAnchor="middle" className="fill-purple-700 text-[9px]">
        PID
      </text>
      {/* SV 和模式 */}
      <text
        x={x}
        y={y + 32}
        textAnchor="middle"
        className={`text-[9px] ${svMissing || modeMissing ? 'fill-red-500' : 'fill-muted-foreground'}`}
        data-testid="pid-sv-mode-label"
      >
        SV: {sv !== null && Number.isFinite(sv) ? sv.toFixed(3) : '—'} m · {modeLabel}
      </text>
      {(svMissing || modeMissing) && (
        <text
          x={x}
          y={y + 44}
          textAnchor="middle"
          className="fill-red-500 text-[8px]"
          data-testid="pid-missing-warning"
        >
          缺字段
        </text>
      )}
    </g>
  )
}

// 排水符号
function DrainSymbol({ x, y }: { x: number; y: number }) {
  return (
    <g>
      {/* 排水三角 */}
      <polygon
        points={`${x},${y} ${x - 10},${y + 15} ${x + 10},${y + 15}`}
        fill="var(--gray-200, #e5e7eb)"
        stroke="var(--gray-400, #9ca3af)"
        strokeWidth={1}
      />
      <text data-testid="drain-label" x={x} y={y + 28} textAnchor="middle" className="fill-muted-foreground text-[9px]">
        排水
      </text>
    </g>
  )
}
