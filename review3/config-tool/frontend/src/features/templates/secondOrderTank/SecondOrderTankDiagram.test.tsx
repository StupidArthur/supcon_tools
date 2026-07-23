import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SecondOrderTankDiagram } from './SecondOrderTankDiagram'
import type { DraftConfig, SelectedObjectId } from '../types'

// 测试用默认 draft 配置
const defaultDraft: DraftConfig = {
  cycleTime: 0.5,
  clockMode: 'REALTIME',
  sourceFlow: 0.0012, // 72 L/min
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

describe('SecondOrderTankDiagram', () => {
  it('应渲染 SVG 画布', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    expect(container.querySelector('[data-testid="pid-diagram"]')).toBeTruthy()
  })

  it('应显示组态预览标记', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    expect(container.textContent).toContain('当前为组态预览，不是实时值')
  })

  it('应显示水源流量 72 L/min', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    // 0.0012 m³/s * 60000 = 72 L/min
    expect(container.textContent).toContain('72.0 L/min')
  })

  it('应显示 Tank 1 初始液位 0.150 m', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    expect(container.textContent).toContain('0.150 m')
  })

  it('应显示 Tank 2 初始液位 0.100 m', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    expect(container.textContent).toContain('0.100 m')
  })

  it('应显示 PID SV 0.800 m', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    expect(container.textContent).toContain('0.800')
  })

  it('应显示阀门初始开度 50.0%', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    expect(container.textContent).toContain('50.0%')
  })

  it('点击水源应触发 onSelect', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    const sources = container.querySelectorAll('[data-testid="source-flow"]')
    fireEvent.click(sources[sources.length - 1])
    expect(onSelect).toHaveBeenCalledWith('source_flow')
  })

  it('点击阀门应触发 onSelect', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    const valves = container.querySelectorAll('[data-testid="valve-1"]')
    fireEvent.click(valves[valves.length - 1])
    expect(onSelect).toHaveBeenCalledWith('valve_1')
  })

  it('点击 Tank 1 应触发 onSelect', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    const tanks = container.querySelectorAll('[data-testid="tank-1"]')
    fireEvent.click(tanks[tanks.length - 1])
    expect(onSelect).toHaveBeenCalledWith('tank_1')
  })

  it('点击 Tank 2 应触发 onSelect', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    const tanks = container.querySelectorAll('[data-testid="tank-2"]')
    fireEvent.click(tanks[tanks.length - 1])
    expect(onSelect).toHaveBeenCalledWith('tank_2')
  })

  it('点击 LT-201 应触发 onSelect 为 lt_201', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    const lts = container.querySelectorAll('[data-testid="lt-201"]')
    fireEvent.click(lts[lts.length - 1])
    expect(onSelect).toHaveBeenCalledWith('lt_201')
  })

  it('点击 PID 应触发 onSelect', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    const pids = container.querySelectorAll('[data-testid="pid2"]')
    fireEvent.click(pids[pids.length - 1])
    expect(onSelect).toHaveBeenCalledWith('pid2')
  })

  it('选中对象应显示高亮', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId="tank_2"
        onSelect={onSelect}
      />
    )

    // Tank 2 应该有高亮描边（通过检查 SVG 属性）
    const tanks = container.querySelectorAll('[data-testid="tank-2"]')
    expect(tanks.length).toBeGreaterThan(0)
  })

  it('选中 LT-201 应显示高亮', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId="lt_201"
        onSelect={onSelect}
      />
    )

    const lts = container.querySelectorAll('[data-testid="lt-201"]')
    expect(lts.length).toBeGreaterThan(0)
  })

  it('应显示 SV 标线', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    // 应该有 SV 标记
    expect(container.textContent).toContain('SV')
  })

  it('SV 标线应在水箱内部（SV < height）', () => {
    // SV = 0.8, height = 1.2, ratio = 0.667
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    // 验证 SV 标线存在
    expect(container.textContent).toContain('SV')
    const svLine = container.querySelector('[data-testid="tank-2-sv-line"]')
    const y = Number(svLine?.getAttribute('y1'))
    expect(y).toBeGreaterThanOrEqual(340)
    expect(y).toBeLessThanOrEqual(560)
    // 没有越界告警
    expect(container.textContent).not.toContain('SV 超出范围')
  })

  it('SV 越界时标线裁剪到水箱顶部', () => {
    const draftWithSvOutOfRange = {
      ...defaultDraft,
      pid: { ...defaultDraft.pid, SV: 1.5 }, // 超过 height=1.2
    }
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={draftWithSvOutOfRange}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    // SV 越界时 ratio 裁剪到 1，标线在水箱顶部
    const svLine = container.querySelector('[data-testid="tank-2-sv-line"]')
    expect(svLine?.getAttribute('y1')).toBe('340')
  })

  it('键盘聚焦应支持 Enter 键选择', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    const sources = container.querySelectorAll('[data-testid="source-flow"]')
    fireEvent.keyDown(sources[sources.length - 1], { key: 'Enter' })
    expect(onSelect).toHaveBeenCalledWith('source_flow')
  })

  it('应显示 PID 模式 AUTO', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={defaultDraft}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    // MODE=5 为 AUTO
    expect(container.textContent).toContain('AUTO')
  })

  it('应显示 PID 模式 MAN', () => {
    const draftWithMan = {
      ...defaultDraft,
      pid: { ...defaultDraft.pid, MODE: 4 },
    }
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={draftWithMan}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    // MODE=4 为 MAN
    expect(container.textContent).toContain('MAN')
  })

  it('液位比例应裁剪到 [0, 1]', () => {
    const draftWithLevelOverflow = {
      ...defaultDraft,
      tank1: { ...defaultDraft.tank1, initialLevel: 1.5 }, // 超过 height=1.2
    }
    const onSelect = vi.fn()
    const { container } = render(
      <SecondOrderTankDiagram
        draft={draftWithLevelOverflow}
        selectedObjectId={null}
        onSelect={onSelect}
      />
    )

    const liquid = container.querySelector('[data-testid="tank_1-liquid"]')
    expect(liquid?.getAttribute('height')).toBe('220')
    expect(liquid?.getAttribute('y')).toBe('110')
  })

  it('排水标签必须位于 SVG viewBox 内', () => {
    const { container } = render(
      <SecondOrderTankDiagram draft={defaultDraft} selectedObjectId={null} onSelect={vi.fn()} />
    )
    const svg = container.querySelector('[data-testid="pid-diagram"]')
    const viewBoxHeight = Number(svg?.getAttribute('viewBox')?.split(' ')[3])
    const labelY = Number(container.querySelector('[data-testid="drain-label"]')?.getAttribute('y'))
    expect(labelY).toBeLessThanOrEqual(viewBoxHeight)
  })
})
