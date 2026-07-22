/**
 * Fixed textbook-style P&ID layout for second-order tank (presentation only).
 * Coordinates are in SVG user units for viewBox="0 0 1000 620".
 */

export const DIAGRAM_VIEWBOX = {
  width: 1000,
  height: 620,
} as const

/** Semantic colors for the diagram (not theme/dark-mode dependent). */
export const DIAGRAM_COLORS = {
  canvasBg: '#FFFFFF',
  pageHint: '#F4F6F8',
  border: '#1F2937',
  pipe: '#1F2937',
  pipeFlow: '#3B82F6',
  liquid: '#3B82F6',
  liquidOpacity: 0.68,
  liquidSurface: '#1D4ED8',
  selected: '#2563EB',
  selectedHalo: '#93C5FD',
  text: '#111827',
  textMuted: '#6B7280',
  warning: '#D97706',
  error: '#DC2626',
  pidFill: '#F0F7FF',
  white: '#FFFFFF',
} as const

export const LAYOUT = {
  tank1: { x: 140, y: 110, width: 220, height: 220 },
  tank2: { x: 530, y: 340, width: 220, height: 220 },
  /** Valve 1 center above Tank 1 */
  valve1: { x: 250, y: 70 },
  /** Top inlet (source_flow hit target) */
  inlet: { x: 250, y: 28 },
  pid: { x: 820, y: 170, width: 140, height: 120 },
  lt: { x: 795, y: 420 },
  /** Decorative outlet valves (not DSL objects) */
  tank1OutletValve: { x: 372, y: 310 },
  tank2OutletValve: { x: 762, y: 540 },
  outlet: { x: 920, y: 540 },
} as const

/** Orthogonal polyline points for process pipes. */
export const PIPE_POINTS = {
  /** Top → Valve 1 */
  inlet: [
    [LAYOUT.inlet.x, 8],
    [LAYOUT.valve1.x, LAYOUT.valve1.y - 18],
  ] as [number, number][],
  /** Valve 1 → Tank 1 top */
  valveToTank1: [
    [LAYOUT.valve1.x, LAYOUT.valve1.y + 18],
    [LAYOUT.tank1.x + LAYOUT.tank1.width / 2, LAYOUT.tank1.y],
  ] as [number, number][],
  /**
   * Tank 1 BR outlet → right → down → right → Tank 2 left inlet.
   */
  tank1ToTank2: [
    [LAYOUT.tank1.x + LAYOUT.tank1.width, LAYOUT.tank1.y + LAYOUT.tank1.height - 20],
    [450, LAYOUT.tank1.y + LAYOUT.tank1.height - 20],
    [450, LAYOUT.tank2.y + LAYOUT.tank2.height / 2],
    [LAYOUT.tank2.x, LAYOUT.tank2.y + LAYOUT.tank2.height / 2],
  ] as [number, number][],
  /** Tank 2 BR outlet → right → Outlet */
  tank2Drain: [
    [LAYOUT.tank2.x + LAYOUT.tank2.width, LAYOUT.tank2.y + LAYOUT.tank2.height - 20],
    [LAYOUT.outlet.x - 20, LAYOUT.tank2.y + LAYOUT.tank2.height - 20],
  ] as [number, number][],
} as const

/** Missing level visual fill ratio (not real data). */
export const MISSING_LEVEL_FALLBACK_RATIO = 0.5
