/**
 * Textbook-style fixed SVG P&ID for second-order tank (presentation layer).
 * Data selection still uses runtime helpers — stop→draft, run→snapshot.
 */
import type { SelectedObjectId, DraftConfig } from '../types'
import { useTemplateStore } from '../useTemplateStore'
import { useRuntimeStore } from '../../runtime/useRuntimeStore'
import {
  selectTankLevel,
  selectValveOpening,
  selectSourceFlow,
  selectPIDSetpoint,
  selectPIDMode,
  shouldShowFlowAnimation,
  formatRuntimeNumber,
  getRuntimeNumber,
} from '../../runtime/dataSelection'
import { DIAGRAM_COLORS, DIAGRAM_VIEWBOX, LAYOUT, PIPE_POINTS } from './diagramLayout'
import {
  ControlValveSymbol,
  InletSourceSymbol,
  LevelTransmitterSymbol,
  OutletArrow,
  OutletValveGlyph,
  PidBlockSymbol,
  ProcessPipe,
  TankSymbol,
} from './diagramSymbols'

interface DiagramProps {
  draft: DraftConfig
  selectedObjectId: SelectedObjectId | null
  onSelect: (id: SelectedObjectId | null) => void
}

export function SecondOrderTankDiagram({ draft, selectedObjectId, onSelect }: DiagramProps) {
  const runtimeState = useTemplateStore((s) => s.runtimeState)
  const runningConfig = useTemplateStore((s) => s.runningConfig)
  const latestSnapshot = useRuntimeStore((s) => s.latestSnapshot)
  const connState = useRuntimeStore((s) => s.connectionState)
  const isStale = useRuntimeStore((s) => s.stale)

  const ctx = {
    runtimeState,
    latestSnapshot,
    draft,
    runningConfig,
  }

  const tank1 = selectTankLevel(ctx, 'tank1')
  const tank2 = selectTankLevel(ctx, 'tank2')
  const tank1Missing = tank1.level === null || !Number.isFinite(tank1.level)
  const tank2Missing = tank2.level === null || !Number.isFinite(tank2.level)

  const pidSvResult = selectPIDSetpoint(ctx)
  const pidSv = pidSvResult.value
  const svRatioRaw =
    pidSv !== null && tank2.height !== null && tank2.height > 0
      ? pidSv / tank2.height
      : null
  const svRatio =
    svRatioRaw !== null && Number.isFinite(svRatioRaw)
      ? Math.max(0, Math.min(1, svRatioRaw))
      : null
  const svMissing = !pidSvResult.present || !pidSvResult.finite

  const valveOpening = selectValveOpening(ctx)
  const valveMissing = !valveOpening.present || !valveOpening.finite || valveOpening.value === null

  const sourceFlowResult = selectSourceFlow(ctx)
  const sourceFlowM3s = sourceFlowResult.value
  const sourceFlowLpm =
    sourceFlowM3s !== null && Number.isFinite(sourceFlowM3s)
      ? sourceFlowM3s * 60_000
      : null
  const sourceMissing = !sourceFlowResult.present || !sourceFlowResult.finite

  const inletFlowAnim = shouldShowFlowAnimation(ctx, connState, isStale, 'inlet')
  const valveToTank1FlowAnim = shouldShowFlowAnimation(ctx, connState, isStale, 'valveToTank1')
  const tank1ToTank2FlowAnim = shouldShowFlowAnimation(ctx, connState, isStale, 'tank1ToTank2')
  const tank2DrainFlowAnim = shouldShowFlowAnimation(ctx, connState, isStale, 'tank2Drain')

  const pidModeResult = selectPIDMode(ctx)
  const pidMode = pidModeResult.value
  const modeLabel =
    pidMode === null
      ? 'M?'
      : pidMode === 1
        ? 'OOS'
        : pidMode === 2
          ? 'IMAN'
          : pidMode === 3
            ? 'TR'
            : pidMode === 4
              ? 'MAN'
              : pidMode === 5
                ? 'AUTO'
                : pidMode === 6
                  ? 'CAS'
                  : pidMode === 7
                    ? 'RCAS'
                    : pidMode === 8
                      ? 'ROUT'
                      : `UNKNOWN(${pidMode})`

  const pidPvStop = getRuntimeNumber(
    ctx,
    (s) => s.pid.PV,
    (d) => d.tank2.initialLevel,
  )
  const pidMv = getRuntimeNumber(
    ctx,
    (s) => s.pid.MV,
    (d) => d.pid.MV,
  )

  const pvText =
    pidPvStop.present && pidPvStop.finite && pidPvStop.value !== null
      ? formatRuntimeNumber(pidPvStop.value, 3, '')
      : '—'
  const svText =
    pidSvResult.present && pidSvResult.finite && pidSv !== null
      ? formatRuntimeNumber(pidSv, 3, '')
      : '—'
  const mvText =
    pidMv.present && pidMv.finite && pidMv.value !== null
      ? `${formatRuntimeNumber(pidMv.value, 1, '')}%`
      : '—'
  const pidMissing =
    !pidPvStop.present ||
    !pidPvStop.finite ||
    !pidSvResult.present ||
    !pidSvResult.finite ||
    !pidMv.present ||
    !pidMv.finite

  const isRunning = runtimeState === 'SIMULATION_RUNNING' || runtimeState === 'REALTIME_RUNNING'

  return (
    <div
      className="h-full w-full"
      style={{ background: DIAGRAM_COLORS.pageHint }}
      data-testid="pid-diagram-host"
    >
      <svg
        viewBox={`0 0 ${DIAGRAM_VIEWBOX.width} ${DIAGRAM_VIEWBOX.height}`}
        preserveAspectRatio="xMidYMid meet"
        className="h-full w-full"
        data-testid="pid-diagram"
        style={{ background: DIAGRAM_COLORS.canvasBg }}
      >
        <rect
          width={DIAGRAM_VIEWBOX.width}
          height={DIAGRAM_VIEWBOX.height}
          fill={DIAGRAM_COLORS.canvasBg}
        />

        {/* Status banner */}
        <text
          x={DIAGRAM_VIEWBOX.width / 2}
          y={22}
          textAnchor="middle"
          fontSize={11}
          fill={
            !isRunning
              ? DIAGRAM_COLORS.textMuted
              : isStale
                ? DIAGRAM_COLORS.warning
                : '#15803d'
          }
        >
          {!isRunning
            ? '当前为组态预览，不是实时值'
            : isStale
              ? '数据已过期（stale）— 显示最后一帧，非草稿回退'
              : `实时运行 · ${connState === 'connected' ? '已连接' : connState}`}
        </text>

        {/* Process pipes (orthogonal only) — no control-loop lines */}
        <ProcessPipe
          testId="pipe-inlet"
          points={PIPE_POINTS.inlet}
          hasFlow={inletFlowAnim}
        />
        <ProcessPipe
          testId="pipe-valve-to-tank1"
          points={PIPE_POINTS.valveToTank1}
          hasFlow={valveToTank1FlowAnim}
        />
        <ProcessPipe
          testId="pipe-tank1-to-tank2"
          points={PIPE_POINTS.tank1ToTank2}
          hasFlow={tank1ToTank2FlowAnim}
        />
        <ProcessPipe
          testId="pipe-tank2-drain"
          points={PIPE_POINTS.tank2Drain}
          hasFlow={tank2DrainFlowAnim}
        />

        <InletSourceSymbol
          x={LAYOUT.inlet.x}
          y={LAYOUT.inlet.y}
          selected={selectedObjectId === 'source_flow'}
          onClick={() => onSelect('source_flow')}
          flowLpm={sourceFlowLpm}
          missing={sourceMissing}
        />

        <ControlValveSymbol
          x={LAYOUT.valve1.x}
          y={LAYOUT.valve1.y}
          selected={selectedObjectId === 'valve_1'}
          onClick={() => onSelect('valve_1')}
          openingPct={valveOpening.value}
          openingMissing={valveMissing}
        />

        <TankSymbol
          x={LAYOUT.tank1.x}
          y={LAYOUT.tank1.y}
          width={LAYOUT.tank1.width}
          height={LAYOUT.tank1.height}
          levelRatio={tank1.ratio}
          levelMissing={tank1Missing}
          selected={selectedObjectId === 'tank_1'}
          onClick={() => onSelect('tank_1')}
          label="Tank 1"
          objectId="tank_1"
          testId="tank-1"
          liquidTestId="tank_1-liquid"
          levelDisplayM={tank1.level}
        />

        <TankSymbol
          x={LAYOUT.tank2.x}
          y={LAYOUT.tank2.y}
          width={LAYOUT.tank2.width}
          height={LAYOUT.tank2.height}
          levelRatio={tank2.ratio}
          levelMissing={tank2Missing}
          selected={selectedObjectId === 'tank_2'}
          onClick={() => onSelect('tank_2')}
          label="Tank 2"
          objectId="tank_2"
          testId="tank-2"
          liquidTestId="tank_2-liquid"
          levelDisplayM={tank2.level}
          showSvLine
          svRatio={svMissing ? null : svRatio}
        />

        {/* Decorative outlet valves (not selectable DSL objects) */}
        <OutletValveGlyph x={LAYOUT.tank1OutletValve.x} y={LAYOUT.tank1OutletValve.y} />
        <OutletValveGlyph x={LAYOUT.tank2OutletValve.x} y={LAYOUT.tank2OutletValve.y} />

        <LevelTransmitterSymbol
          x={LAYOUT.lt.x}
          y={LAYOUT.lt.y}
          selected={selectedObjectId === 'lt_201'}
          onClick={() => onSelect('lt_201')}
          levelM={tank2.level}
          missing={tank2Missing}
        />

        <PidBlockSymbol
          x={LAYOUT.pid.x}
          y={LAYOUT.pid.y}
          width={LAYOUT.pid.width}
          height={LAYOUT.pid.height}
          selected={selectedObjectId === 'pid2'}
          onClick={() => onSelect('pid2')}
          pv={pvText}
          sv={svText}
          mv={mvText}
          modeLabel={modeLabel}
          missing={pidMissing}
        />

        <OutletArrow x={LAYOUT.outlet.x} y={LAYOUT.outlet.y} />

        {/* Keep unused-but-referenced warning binding for pid missing */}
        {pidMissing ? (
          <text
            x={LAYOUT.pid.x + LAYOUT.pid.width / 2}
            y={LAYOUT.pid.y - 8}
            textAnchor="middle"
            fontSize={9}
            fill={DIAGRAM_COLORS.error}
            data-testid="pid-missing-warning"
          >
            缺字段
          </text>
        ) : null}
      </svg>
    </div>
  )
}
