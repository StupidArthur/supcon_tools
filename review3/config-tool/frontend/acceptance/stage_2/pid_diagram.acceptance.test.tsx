/**
 * Stage 2 reviewer acceptance: fixed SVG P&ID, selection, stop-state values, no fake flow.
 */
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { SecondOrderTankDiagram } from '../../src/features/templates/secondOrderTank/SecondOrderTankDiagram'
import type { DraftConfig } from '../../src/features/templates/types'

const defaultDraft: DraftConfig = {
  cycleTime: 0.5,
  clockMode: 'REALTIME',
  sourceFlow: 0.0012,
  valve: {
    fullTravelTime: 12,
    initialOpening: 50,
    flowCoefficient: 1,
    minOpening: 0,
    maxOpening: 100,
  },
  tank1: { height: 1.2, radius: 0.15, outletArea: 0.00025, initialLevel: 0.15 },
  tank2: { height: 1.2, radius: 0.15, outletArea: 0.0002, initialLevel: 0.1 },
  pid: {
    PB: 30, TI: 90, TD: 20, KD: 10, SV: 0.8, MV: 0, MODE: 5, SWPN: 1,
    SVSCL: 0, SVSCH: 1.2, SVL: 0, SVH: 1.2,
    MVSCL: 0, MVSCH: 100, MVL: 0, MVH: 100,
  },
}

describe('stage 2 pid diagram acceptance', () => {
  it('renders a fixed SVG diagram with stable object test ids', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram draft={defaultDraft} selectedObjectId={null} onSelect={onSelect} />,
    )
    expect(container.querySelector('[data-testid="pid-diagram"]')).toBeTruthy()
    expect(container.querySelector('svg')).toBeTruthy()
    for (const id of ['source-flow', 'valve-1', 'tank-1', 'tank-2', 'lt-201', 'pid2']) {
      expect(container.querySelector(`[data-testid="${id}"]`)).toBeTruthy()
    }
    expect(container.querySelector('.react-flow')).toBeNull()
  })

  it('supports click and Enter keyboard selection', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram draft={defaultDraft} selectedObjectId={null} onSelect={onSelect} />,
    )
    fireEvent.click(container.querySelector('[data-testid="tank-2"]')!)
    expect(onSelect).toHaveBeenCalledWith('tank_2')
    const valve = container.querySelector('[data-testid="valve-1"]')!
    fireEvent.keyDown(valve, { key: 'Enter' })
    expect(onSelect).toHaveBeenCalledWith('valve_1')
  })

  it('documents Space keyboard selection contract', () => {
    // Contract (todo/7.md §9): Enter/Space must both select. Current diagram only wires Enter.
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram draft={defaultDraft} selectedObjectId={null} onSelect={onSelect} />,
    )
    const valve = container.querySelector('[data-testid="valve-1"]')!
    fireEvent.keyDown(valve, { key: ' ' })
    expect(onSelect).toHaveBeenCalledWith('valve_1')
  })

  it('shows stop-state levels/openings and configuration-preview banner', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram draft={defaultDraft} selectedObjectId={null} onSelect={onSelect} />,
    )
    expect(container.textContent).toContain('当前为组态预览，不是实时值')
    expect(container.querySelector('[data-testid="tank-2-sv-line"]')).toBeTruthy()
  })

  it('does not use infinite CSS animation classes for fake flow', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram draft={defaultDraft} selectedObjectId={null} onSelect={onSelect} />,
    )
    const animated = container.querySelectorAll('[class*="animate-"], [style*="animation"]')
    expect(animated.length).toBe(0)
  })
})
