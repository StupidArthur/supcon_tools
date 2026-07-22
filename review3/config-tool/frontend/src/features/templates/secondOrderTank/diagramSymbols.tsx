/**
 * Textbook P&ID symbols for second-order tank (presentation only).
 */
import type { KeyboardEvent, ReactNode } from 'react'
import { DIAGRAM_COLORS, MISSING_LEVEL_FALLBACK_RATIO } from './diagramLayout'

export function handleSelectableKeyDown(
  event: KeyboardEvent,
  onActivate: () => void,
): void {
  const key = event.key
  if (key === 'Enter' || key === ' ' || key === 'Spacebar') {
    event.preventDefault()
    onActivate()
  }
}

function selectionStroke(selected: boolean): { stroke: string; strokeWidth: number } {
  return {
    stroke: selected ? DIAGRAM_COLORS.selected : DIAGRAM_COLORS.border,
    strokeWidth: selected ? 3 : 2,
  }
}

/** Soft halo behind a selected symbol bbox. */
export function SelectionHalo({
  x,
  y,
  width,
  height,
  visible,
}: {
  x: number
  y: number
  width: number
  height: number
  visible: boolean
}) {
  if (!visible) return null
  return (
    <rect
      x={x - 4}
      y={y - 4}
      width={width + 8}
      height={height + 8}
      rx={4}
      fill="none"
      stroke={DIAGRAM_COLORS.selectedHalo}
      strokeWidth={4}
      opacity={0.9}
      pointerEvents="none"
    />
  )
}

/**
 * Orthogonal process pipe. Flow uses static dash (no CSS animate-* classes —
 * Stage 2 acceptance forbids infinite animation classes).
 */
export function ProcessPipe({
  points,
  hasFlow,
  testId,
  markerEnd,
}: {
  points: [number, number][]
  hasFlow: boolean
  testId: string
  markerEnd?: string
}) {
  const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0]},${p[1]}`).join(' ')
  return (
    <path
      d={d}
      data-testid={testId}
      stroke={hasFlow ? DIAGRAM_COLORS.pipeFlow : DIAGRAM_COLORS.pipe}
      strokeWidth={3.5}
      fill="none"
      strokeLinejoin="round"
      strokeLinecap="square"
      strokeDasharray={hasFlow ? '8 5' : undefined}
      markerEnd={markerEnd}
    />
  )
}

/** Small decorative outlet valve (not a DSL selectable object). */
export function OutletValveGlyph({ x, y }: { x: number; y: number }) {
  const s = 10
  return (
    <g pointerEvents="none" aria-hidden>
      <polygon
        points={`${x},${y - s} ${x + s},${y} ${x},${y + s} ${x - s},${y}`}
        fill={DIAGRAM_COLORS.white}
        stroke={DIAGRAM_COLORS.border}
        strokeWidth={1.5}
      />
    </g>
  )
}

/** Shared rectangular tank with bottom-up liquid fill. */
export function TankSymbol({
  x,
  y,
  width,
  height,
  levelRatio,
  levelMissing,
  selected,
  onClick,
  label,
  objectId,
  testId,
  liquidTestId,
  levelDisplayM,
  showSvLine,
  svRatio,
}: {
  x: number
  y: number
  width: number
  height: number
  levelRatio: number | null
  levelMissing: boolean
  selected: boolean
  onClick: () => void
  label: string
  objectId: string
  testId: string
  liquidTestId: string
  levelDisplayM: number | null
  showSvLine?: boolean
  svRatio?: number | null
}) {
  const fillRatio = levelMissing
    ? MISSING_LEVEL_FALLBACK_RATIO
    : Math.max(0, Math.min(1, levelRatio ?? 0))
  const liquidH = height * fillRatio
  const liquidY = y + height - liquidH
  const stroke = selectionStroke(selected)
  const levelText =
    !levelMissing && levelDisplayM !== null && Number.isFinite(levelDisplayM)
      ? `${levelDisplayM.toFixed(3)} m`
      : '—'

  return (
    <g
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-label={label}
      onClick={onClick}
      onKeyDown={(e) => handleSelectableKeyDown(e, onClick)}
      className="cursor-pointer"
      data-testid={testId}
      data-object-id={objectId}
      style={{ outline: 'none' }}
    >
      <SelectionHalo x={x} y={y} width={width} height={height} visible={selected} />
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill={DIAGRAM_COLORS.white}
        stroke={stroke.stroke}
        strokeWidth={stroke.strokeWidth}
        rx={2}
      />
      <rect
        x={x}
        y={liquidY}
        width={width}
        height={liquidH}
        fill={DIAGRAM_COLORS.liquid}
        opacity={DIAGRAM_COLORS.liquidOpacity}
        data-testid={liquidTestId}
      />
      {liquidH > 1 ? (
        <line
          x1={x}
          y1={liquidY}
          x2={x + width}
          y2={liquidY}
          stroke={DIAGRAM_COLORS.liquidSurface}
          strokeWidth={2}
        />
      ) : null}
      {showSvLine && svRatio != null && Number.isFinite(svRatio) ? (
        <line
          x1={x + 4}
          y1={y + height - height * Math.max(0, Math.min(1, svRatio))}
          x2={x + width - 4}
          y2={y + height - height * Math.max(0, Math.min(1, svRatio))}
          stroke={DIAGRAM_COLORS.warning}
          strokeWidth={1.5}
          strokeDasharray="4 3"
          data-testid="tank-2-sv-line"
        />
      ) : null}
      {showSvLine && (svRatio == null || !Number.isFinite(svRatio)) ? (
        <text
          x={x + width / 2}
          y={y + 36}
          textAnchor="middle"
          fontSize={9}
          fill={DIAGRAM_COLORS.error}
          data-testid="tank-2-sv-missing"
        >
          SV —
        </text>
      ) : null}
      <text
        x={x + width / 2}
        y={y + 18}
        textAnchor="middle"
        fontSize={13}
        fontWeight={selected ? 700 : 600}
        fill={DIAGRAM_COLORS.text}
      >
        {label}
      </text>
      <text
        x={x + width / 2}
        y={y + height + 16}
        textAnchor="middle"
        fontSize={11}
        fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
        fill={levelMissing ? DIAGRAM_COLORS.error : DIAGRAM_COLORS.textMuted}
        data-testid={`${objectId}-level-text`}
      >
        {levelText}
        {levelMissing ? ' (缺失)' : ''}
      </text>
    </g>
  )
}

/** Control valve (two opposing triangles). */
export function ControlValveSymbol({
  x,
  y,
  selected,
  onClick,
  openingPct,
  openingMissing,
}: {
  x: number
  y: number
  selected: boolean
  onClick: () => void
  openingPct: number | null
  openingMissing: boolean
}) {
  const stroke = selectionStroke(selected)
  const display =
    !openingMissing && openingPct !== null && Number.isFinite(openingPct)
      ? `${openingPct.toFixed(1)}%`
      : '—'

  return (
    <g
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-label="Valve 1"
      onClick={onClick}
      onKeyDown={(e) => handleSelectableKeyDown(e, onClick)}
      className="cursor-pointer"
      data-testid="valve-1"
      data-object-id="valve_1"
      style={{ outline: 'none' }}
    >
      <SelectionHalo x={x - 28} y={y - 22} width={56} height={44} visible={selected} />
      <polygon
        points={`${x - 22},${y} ${x},${y - 16} ${x + 22},${y} ${x},${y + 16}`}
        fill={DIAGRAM_COLORS.white}
        stroke={stroke.stroke}
        strokeWidth={stroke.strokeWidth}
      />
      <line x1={x} y1={y - 16} x2={x} y2={y - 26} stroke={DIAGRAM_COLORS.border} strokeWidth={2} />
      <line x1={x - 8} y1={y - 26} x2={x + 8} y2={y - 26} stroke={DIAGRAM_COLORS.border} strokeWidth={2} />
      <text
        x={x}
        y={y - 34}
        textAnchor="middle"
        fontSize={11}
        fontWeight={selected ? 700 : 600}
        fill={DIAGRAM_COLORS.text}
      >
        Valve 1
      </text>
      <text
        x={x}
        y={y + 32}
        textAnchor="middle"
        fontSize={10}
        fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
        fill={openingMissing ? DIAGRAM_COLORS.error : DIAGRAM_COLORS.textMuted}
        data-testid="valve-current-opening"
      >
        {display}
      </text>
    </g>
  )
}

/** Top inlet representing source_flow (no large circle). */
export function InletSourceSymbol({
  x,
  y,
  selected,
  onClick,
  flowLpm,
  missing,
}: {
  x: number
  y: number
  selected: boolean
  onClick: () => void
  flowLpm: number | null
  missing: boolean
}) {
  const stroke = selectionStroke(selected)
  const display =
    !missing && flowLpm !== null && Number.isFinite(flowLpm)
      ? `${flowLpm.toFixed(1)} L/min`
      : '—'

  return (
    <g
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-label="Inlet source flow"
      onClick={onClick}
      onKeyDown={(e) => handleSelectableKeyDown(e, onClick)}
      className="cursor-pointer"
      data-testid="source-flow"
      data-object-id="source_flow"
      style={{ outline: 'none' }}
    >
      <SelectionHalo x={x - 36} y={y - 18} width={72} height={40} visible={selected} />
      <polygon
        points={`${x},${y + 10} ${x - 10},${y - 6} ${x + 10},${y - 6}`}
        fill={DIAGRAM_COLORS.white}
        stroke={stroke.stroke}
        strokeWidth={stroke.strokeWidth}
      />
      <text
        x={x}
        y={y - 12}
        textAnchor="middle"
        fontSize={11}
        fontWeight={selected ? 700 : 600}
        fill={DIAGRAM_COLORS.text}
      >
        Inlet
      </text>
      <text
        x={x + 48}
        y={y + 4}
        textAnchor="start"
        fontSize={10}
        fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
        fill={missing ? DIAGRAM_COLORS.error : DIAGRAM_COLORS.textMuted}
        data-testid="source-flow-value"
      >
        {display}
      </text>
    </g>
  )
}

export function LevelTransmitterSymbol({
  x,
  y,
  selected,
  onClick,
  levelM,
  missing,
}: {
  x: number
  y: number
  selected: boolean
  onClick: () => void
  levelM: number | null
  missing: boolean
}) {
  const stroke = selectionStroke(selected)
  const display =
    !missing && levelM !== null && Number.isFinite(levelM)
      ? `${levelM.toFixed(3)} m`
      : '—'

  return (
    <g
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-label="LT-201 level transmitter"
      onClick={onClick}
      onKeyDown={(e) => handleSelectableKeyDown(e, onClick)}
      className="cursor-pointer"
      data-testid="lt-201"
      data-object-id="lt_201"
      style={{ outline: 'none' }}
    >
      <SelectionHalo x={x - 22} y={y - 22} width={44} height={56} visible={selected} />
      <circle
        cx={x}
        cy={y}
        r={18}
        fill={DIAGRAM_COLORS.white}
        stroke={stroke.stroke}
        strokeWidth={stroke.strokeWidth}
      />
      <text
        x={x}
        y={y + 4}
        textAnchor="middle"
        fontSize={11}
        fontWeight={700}
        fill={DIAGRAM_COLORS.text}
      >
        LT
      </text>
      <text
        x={x}
        y={y + 34}
        textAnchor="middle"
        fontSize={10}
        fontWeight={selected ? 700 : 500}
        fill={DIAGRAM_COLORS.text}
      >
        LT-201
      </text>
      <text
        x={x}
        y={y + 48}
        textAnchor="middle"
        fontSize={10}
        fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
        fill={missing ? DIAGRAM_COLORS.error : DIAGRAM_COLORS.textMuted}
      >
        {display}
      </text>
    </g>
  )
}

export function PidBlockSymbol({
  x,
  y,
  width,
  height,
  selected,
  onClick,
  pv,
  sv,
  mv,
  modeLabel,
  missing,
}: {
  x: number
  y: number
  width: number
  height: number
  selected: boolean
  onClick: () => void
  pv: string
  sv: string
  mv: string
  modeLabel: string
  missing: boolean
}) {
  const stroke = selectionStroke(selected)
  const rows: Array<{ k: string; v: string }> = [
    { k: 'PV', v: pv },
    { k: 'SV', v: sv },
    { k: 'MV', v: mv },
  ]

  return (
    <g
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-label="PID LIC-201"
      onClick={onClick}
      onKeyDown={(e) => handleSelectableKeyDown(e, onClick)}
      className="cursor-pointer"
      data-testid="pid2"
      data-object-id="pid2"
      style={{ outline: 'none' }}
    >
      <SelectionHalo x={x} y={y} width={width} height={height} visible={selected} />
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill={DIAGRAM_COLORS.pidFill}
        stroke={stroke.stroke}
        strokeWidth={stroke.strokeWidth}
        rx={2}
      />
      <text
        x={x + 10}
        y={y + 18}
        fontSize={12}
        fontWeight={700}
        fill={DIAGRAM_COLORS.text}
      >
        PID
      </text>
      <text x={x + 10} y={y + 34} fontSize={10} fill={DIAGRAM_COLORS.textMuted}>
        LIC-201
      </text>
      {rows.map((row, i) => (
        <g key={row.k}>
          <text
            x={x + 10}
            y={y + 54 + i * 16}
            fontSize={11}
            fill={DIAGRAM_COLORS.textMuted}
          >
            {row.k}
          </text>
          <text
            x={x + width - 10}
            y={y + 54 + i * 16}
            textAnchor="end"
            fontSize={11}
            fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
            fill={missing ? DIAGRAM_COLORS.error : DIAGRAM_COLORS.text}
          >
            {row.v}
          </text>
        </g>
      ))}
      <text
        x={x + width / 2}
        y={y + height - 10}
        textAnchor="middle"
        fontSize={11}
        fontWeight={600}
        fill={DIAGRAM_COLORS.text}
        data-testid="pid-sv-mode-label"
      >
        {modeLabel}
      </text>
    </g>
  )
}

export function OutletArrow({ x, y }: { x: number; y: number }) {
  return (
    <g pointerEvents="none" aria-hidden>
      <polygon
        points={`${x},${y} ${x - 14},${y - 7} ${x - 14},${y + 7}`}
        fill={DIAGRAM_COLORS.border}
      />
      <text
        x={x}
        y={y + 22}
        textAnchor="middle"
        fontSize={10}
        fill={DIAGRAM_COLORS.textMuted}
        data-testid="drain-label"
      >
        Outlet
      </text>
    </g>
  )
}

export function DiagramBanner({ children }: { children: ReactNode }) {
  return (
    <foreignObject x={20} y={8} width={960} height={28}>
      <div
        style={{
          fontSize: 11,
          color: DIAGRAM_COLORS.textMuted,
          textAlign: 'center',
          lineHeight: '28px',
        }}
      >
        {children}
      </div>
    </foreignObject>
  )
}
