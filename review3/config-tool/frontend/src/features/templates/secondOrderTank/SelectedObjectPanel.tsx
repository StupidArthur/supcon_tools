/**
 * Selected-object banner + right-panel switching helper (presentation).
 */
import type { SelectedObjectId } from '../types'
import { SECOND_ORDER_TANK_OBJECTS } from './definition'

const DISPLAY_NAME: Record<SelectedObjectId, string> = {
  source_flow: '水源 / Inlet',
  valve_1: 'Valve 1',
  tank_1: 'Tank 1',
  tank_2: 'Tank 2',
  lt_201: 'LT-201',
  pid2: 'PID',
}

export function selectedObjectLabel(id: SelectedObjectId | null): string | null {
  if (!id) return null
  const meta = SECOND_ORDER_TANK_OBJECTS.find((o) => o.id === id)
  return meta?.displayName ?? DISPLAY_NAME[id] ?? id
}

export function SelectedObjectMessage({
  selectedObjectId,
}: {
  selectedObjectId: SelectedObjectId | null
}) {
  const label = selectedObjectLabel(selectedObjectId)
  if (!label) {
    return (
      <div
        className="border-b border-border px-3 py-2 text-xs text-muted-foreground"
        data-testid="selected-object-message"
      >
        未选择对象 — 点击流程图中的设备查看参数
      </div>
    )
  }
  return (
    <div
      className="border-b border-border bg-blue-50 px-3 py-2 text-xs font-medium text-blue-900"
      data-testid="selected-object-message"
    >
      已选择：{DISPLAY_NAME[selectedObjectId!] ?? label}
    </div>
  )
}

/** Whether the right column should emphasize PID Faceplate over property inspector. */
export function shouldShowPidControlPanel(selectedObjectId: SelectedObjectId | null): boolean {
  return selectedObjectId === 'pid2'
}
