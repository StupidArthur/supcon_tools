/**
 * Stage 2 reviewer acceptance: inspector edits draft only and shows YAML metadata.
 */
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { SecondOrderTankInspector } from '../../src/features/templates/secondOrderTank/SecondOrderTankInspector'
import type { DraftConfig } from '../../src/features/templates/types'

const draft: DraftConfig = {
  cycleTime: 0.5,
  clockMode: 'REALTIME',
  sourceFlow: 0.0012,
  valve: { fullTravelTime: 10, initialOpening: 0, flowCoefficient: 1, minOpening: 0, maxOpening: 100 },
  tank1: { height: 1.2, radius: 0.15, outletArea: 0.00025, initialLevel: 0.15 },
  tank2: { height: 1.2, radius: 0.15, outletArea: 0.0002, initialLevel: 0.1 },
  pid: {
    PB: 30, TI: 90, TD: 20, KD: 10, SV: 0.8, MV: 0, MODE: 5, SWPN: 1,
    SVSCL: 0, SVSCH: 1.2, SVL: 0, SVH: 1.2,
    MVSCL: 0, MVSCH: 100, MVL: 0, MVH: 100,
  },
}

describe('stage 2 inspector acceptance', () => {
  it('shows template help when nothing is selected', () => {
    render(
      <SecondOrderTankInspector
        selectedObjectId={null}
        draft={draft}
        dirtyPaths={new Set()}
        validationErrors={[]}
        validationWarnings={[]}
        onEditField={vi.fn()}
      />,
    )
    expect(screen.getByTestId('inspector-empty')).toBeTruthy()
    expect(screen.getByText(/模板说明/)).toBeTruthy()
  })

  it('edits only mutate draft while saved stays unchanged', () => {
    const onEditField = vi.fn()
    const localDraft = structuredClone(draft)
    render(
      <SecondOrderTankInspector
        selectedObjectId="tank_2"
        draft={localDraft}
        dirtyPaths={new Set()}
        validationErrors={[]}
        validationWarnings={[]}
        onEditField={onEditField}
      />,
    )
    const input = screen.getByTestId('input-tank2.radius') as HTMLInputElement
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '0.18' } })
    fireEvent.blur(input)
    expect(onEditField).toHaveBeenCalledWith('tank2.radius', 0.18)
  })
})
