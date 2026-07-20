import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ObjectInspector } from './ObjectInspector'
import { useTemplateStore } from './useTemplateStore'

// Mock useTemplateStore
vi.mock('./useTemplateStore', () => ({
  useTemplateStore: vi.fn(),
}))

describe('ObjectInspector', () => {
  const defaultDraft = {
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
    tank1: {
      height: 1.2,
      radius: 0.15,
      outletArea: 0.00025,
      initialLevel: 0.15,
    },
    tank2: {
      height: 1.2,
      radius: 0.15,
      outletArea: 0.00020,
      initialLevel: 0.10,
    },
    pid: {
      PB: 30,
      TI: 90,
      TD: 20,
      KD: 10,
      SV: 0.8,
      MV: 0,
      MODE: 5,
      SWPN: 1,
      SVSCL: 0,
      SVSCH: 1.2,
      SVL: 0,
      SVH: 1.2,
      MVSCL: 0,
      MVSCH: 100,
      MVL: 0,
      MVH: 100,
    },
  }

  const defaultState = {
    templateId: 'second_order_tank' as const,
    selectedObjectId: null as string | null,
    draft: defaultDraft,
    dirtyPaths: new Set<string>(),
    validationErrors: [],
    validationWarnings: [],
    editField: vi.fn(),
  }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
      if (typeof selector === 'function') {
        return selector(defaultState)
      }
      return defaultState
    })
  })

  it('应显示加载状态（无 draft）', () => {
    const stateNoDraft = {
      ...defaultState,
      draft: null,
    }
    vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
      if (typeof selector === 'function') {
        return selector(stateNoDraft)
      }
      return stateNoDraft
    })

    const { container } = render(<ObjectInspector />)
    expect(container.textContent).toContain('正在加载...')
  })

  it('应渲染检查器（有 draft）', () => {
    const { container } = render(<ObjectInspector />)
    expect(container.querySelector('[data-testid="inspector-empty"]')).toBeTruthy()
  })

  it('应显示模板说明（未选中对象）', () => {
    const { container } = render(<ObjectInspector />)
    expect(container.querySelector('[data-testid="inspector-empty"]')).toBeTruthy()
    expect(container.textContent).toContain('模板说明')
  })

  it('应显示选中对象的检查器', () => {
    const stateWithSelection = {
      ...defaultState,
      selectedObjectId: 'tank_2' as const,
    }
    vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
      if (typeof selector === 'function') {
        return selector(stateWithSelection)
      }
      return stateWithSelection
    })

    render(<ObjectInspector />)
    expect(screen.getByTestId('inspector')).toBeTruthy()
    expect(screen.getByText('下游水箱')).toBeTruthy()
  })

  it('应显示不支持的模板类型', () => {
    const stateUnknown = {
      ...defaultState,
      templateId: 'unknown' as any,
    }
    vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
      if (typeof selector === 'function') {
        return selector(stateUnknown)
      }
      return stateUnknown
    })

    render(<ObjectInspector />)
    expect(screen.getByText('不支持的模板类型')).toBeTruthy()
  })
})
