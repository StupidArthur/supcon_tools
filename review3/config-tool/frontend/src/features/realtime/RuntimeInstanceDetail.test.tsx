import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRuntimeStore } from '../runtime/useRuntimeStore'
import { RuntimeInstanceDetail } from './RuntimeInstanceDetail'

const tagDefs: Array<{
  name: string
  attribute: string
  instance: string
  description: string
  writable: boolean
  forceable: boolean
}> = [
  { name: 'pid1.PV', attribute: 'PV', instance: 'pid1', description: 'pid1 测量值', writable: true, forceable: true },
  { name: 'pid1.SV', attribute: 'SV', instance: 'pid1', description: 'pid1 设定值', writable: true, forceable: false },
  { name: 'pid1.MV', attribute: 'MV', instance: 'pid1', description: 'pid1 输出', writable: false, forceable: false },
  { name: 'pid2.PV', attribute: 'PV', instance: 'pid2', description: 'pid2 测量值', writable: true, forceable: true },
  { name: 'pid2.SV', attribute: 'SV', instance: 'pid2', description: 'pid2 设定值', writable: true, forceable: false },
  { name: 'tank_2.level', attribute: 'level', instance: 'tank_2', description: '液位', writable: false, forceable: true },
]

function installWailsMock(setRuntimeValueMock?: ReturnType<typeof vi.fn>): void {
  // 模拟 wails runtime：window.go.bindings.RealtimeProjectBinding.*
  const w = window as any
  if (!w.go) w.go = { bindings: {} }
  if (!w.go.bindings) w.go.bindings = {}
  // 默认空实现，避免 undefined 调用崩溃
  const noop = () => Promise.resolve({ ok: true })
  w.go.bindings.RealtimeProjectBinding = {
    SetForce: noop,
    GetForces: () => Promise.resolve({ forces: {} }),
    GetQualities: () => Promise.resolve({ qualities: {} }),
    SetQuality: noop,
    ClearForce: noop,
    ClearQuality: noop,
    SetRuntimeValue: setRuntimeValueMock ?? (() => Promise.resolve({ ok: true })),
  }
}

describe('RuntimeInstanceDetail', () => {
  beforeEach(() => {
    useRuntimeStore.getState()._reset()
    useRuntimeStore.setState({
      tagCatalog: tagDefs as any,
      apiHost: '127.0.0.1',
      apiPort: 8000,
      runtimeName: 'second_order_tank',
      connectionState: 'connected',
      latestFrame: { values: {}, receivedAt: Date.now() } as any,
      rawSnapshot: {},
    })
    installWailsMock()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    cleanup()
    useRuntimeStore.getState()._reset()
    vi.restoreAllMocks()
  })

  it('过滤 tagCatalog 只显示当前 instance 的 tag', () => {
    const { container } = render(<RuntimeInstanceDetail instanceName="pid1" onBack={() => {}} />)
    expect(container.querySelector('[data-testid="runtime-detail-row-pid1.PV"]')).toBeTruthy()
    expect(container.querySelector('[data-testid="runtime-detail-row-pid1.SV"]')).toBeTruthy()
    expect(container.querySelector('[data-testid="runtime-detail-row-pid1.MV"]')).toBeTruthy()
    expect(container.querySelector('[data-testid="runtime-detail-row-pid2.PV"]')).toBeNull()
    expect(container.querySelector('[data-testid="runtime-detail-row-pid2.SV"]')).toBeNull()
    expect(container.querySelector('[data-testid="runtime-detail-row-tank_2.level"]')).toBeNull()
  })

  it('切换到 pid2 后只显示 pid2 的 tag', () => {
    const { container, rerender } = render(
      <RuntimeInstanceDetail instanceName="pid1" onBack={() => {}} />,
    )
    expect(container.querySelector('[data-testid="runtime-detail-row-pid1.PV"]')).toBeTruthy()
    expect(container.querySelector('[data-testid="runtime-detail-row-pid2.PV"]')).toBeNull()

    rerender(<RuntimeInstanceDetail instanceName="pid2" onBack={() => {}} />)
    expect(container.querySelector('[data-testid="runtime-detail-row-pid1.PV"]')).toBeNull()
    expect(container.querySelector('[data-testid="runtime-detail-row-pid2.PV"]')).toBeTruthy()
    expect(container.querySelector('[data-testid="runtime-detail-row-pid2.SV"]')).toBeTruthy()
  })

  it('不调用 /api/instances/default/tags', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ tags: [] }) })
    ;(globalThis as any).fetch = fetchSpy

    render(<RuntimeInstanceDetail instanceName="pid1" onBack={() => {}} />)
    await new Promise((r) => setTimeout(r, 50))

    const calls = fetchSpy.mock.calls.map((c: any[]) => String(c[0]))
    const hits = calls.filter((u: string) => u.includes('/api/instances/default/tags'))
    expect(hits.length).toBe(0)
  })

  it('runtimeName 缺失时不发出 SetRuntimeValue', async () => {
    const setValue = vi.fn().mockResolvedValue({ ok: true })
    installWailsMock(setValue)

    // 先设置 runtimeName 存在，让 select 渲染出来
    const { container } = render(<RuntimeInstanceDetail instanceName="pid1" onBack={() => {}} />)
    let row = container.querySelector('[data-testid="runtime-detail-row-pid1.SV"]') as HTMLElement
    expect(row.querySelector('select')).toBeTruthy()

    // 现在清空 runtimeName，操作必须被拒绝
    act(() => useRuntimeStore.setState({ runtimeName: null }))

    row = container.querySelector('[data-testid="runtime-detail-row-pid1.SV"]') as HTMLElement
    // select 应已不可见（writable gated by hasRuntimeName）
    expect(row.querySelector('select')).toBeNull()
    expect(setValue).not.toHaveBeenCalled()
  })

  it('connecting 状态显示"正在加载实例参数"，不显示"没有参数"', () => {
    act(() => useRuntimeStore.setState({ connectionState: 'connecting' }))
    const { container } = render(<RuntimeInstanceDetail instanceName="pid1" onBack={() => {}} />)
    expect(container.textContent).toContain('正在加载实例参数')
    expect(container.textContent).not.toContain('当前实例没有')
  })

  it('connected 且 catalog 真实为空时显示"当前实例没有可用参数"', () => {
    act(() => useRuntimeStore.setState({ tagCatalog: [] }))
    const { container } = render(
      <RuntimeInstanceDetail instanceName="unknown_inst" onBack={() => {}} />,
    )
    expect(container.textContent).toContain('当前实例没有可用参数')
  })

  it('connectionState 错误时显示 lastError 内容', () => {
    act(() =>
      useRuntimeStore.setState({
        connectionState: 'error',
        lastError: '/api/instances/unknown/tags HTTP 404',
      }),
    )
    const { container } = render(<RuntimeInstanceDetail instanceName="pid1" onBack={() => {}} />)
    expect(container.textContent).toContain('/api/instances/unknown/tags HTTP 404')
  })

  it('未运行时显示"服务尚未启动"', () => {
    act(() => useRuntimeStore.setState({ connectionState: 'idle' }))
    const { container } = render(<RuntimeInstanceDetail instanceName="pid1" onBack={() => {}} />)
    expect(container.textContent).toContain('服务尚未启动')
    expect(container.textContent).toContain('暂无实时参数')
  })

  // ———— §四.1 操作权限测试 ————
  function getOptionsOf(row: Element): string[] {
    const select = row.querySelector('select') as HTMLSelectElement
    return Array.from(select.options).map((o) => o.value).filter((v) => v !== '')
  }

  it('A: 不可 force 的 tag 没有"固定 UA 输出值"（pid1.SV forceable=false）', () => {
    // pid1.SV: writable=true, forceable=false, attribute="SV"
    const { container } = render(<RuntimeInstanceDetail instanceName="pid1" onBack={() => {}} />)
    const row = container.querySelector(
      '[data-testid="runtime-detail-row-pid1.SV"]',
    ) as HTMLElement
    expect(row).toBeTruthy()
    const values = getOptionsOf(row)
    expect(values).not.toContain('fix')
    expect(values).toContain('sv')
    expect(values).toContain('quality')
  })

  it('B: 非 SV tag 没有"设置设定值"（pid1.MV 仅 fix 显示；若有 quality 也允许）', () => {
    // pid1.MV: writable=false, forceable=false, attribute="MV"
    const { container } = render(<RuntimeInstanceDetail instanceName="pid1" onBack={() => {}} />)
    const row = container.querySelector(
      '[data-testid="runtime-detail-row-pid1.MV"]',
    ) as HTMLElement
    expect(row).toBeTruthy()
    const values = getOptionsOf(row)
    expect(values).not.toContain('fix')
    expect(values).not.toContain('sv')
    expect(values).toContain('quality')
  })

  it('B2: forceable=true 的 PV 仍有固定操作，但没有 SV 操作', () => {
    // pid1.PV: writable=true, forceable=true, attribute="PV"
    const { container } = render(<RuntimeInstanceDetail instanceName="pid1" onBack={() => {}} />)
    const row = container.querySelector(
      '[data-testid="runtime-detail-row-pid1.PV"]',
    ) as HTMLElement
    expect(row).toBeTruthy()
    const values = getOptionsOf(row)
    expect(values).toContain('fix')
    expect(values).not.toContain('sv')
    expect(values).toContain('quality')
  })

  it('C: 连接断开后确认按钮 disabled 且不会发出 SetRuntimeValue', async () => {
    const setValue = vi.fn().mockResolvedValue({ ok: true })
    installWailsMock(setValue)

    const { container } = render(<RuntimeInstanceDetail instanceName="pid1" onBack={() => {}} />)

    // pid1.SV 行（attribute="SV"），打开操作框
    const row = container.querySelector(
      '[data-testid="runtime-detail-row-pid1.SV"]',
    ) as HTMLElement
    const select = row.querySelector('select') as HTMLSelectElement
    act(() => {
      select.value = 'sv'
      select.dispatchEvent(new Event('change', { bubbles: true }))
    })

    let confirm = container.querySelector(
      '[data-testid="runtime-detail-op-confirm"]',
    ) as HTMLButtonElement
    expect(confirm.disabled).toBe(false)

    // 断开连接 + 清空 runtimeName
    act(() =>
      useRuntimeStore.setState({ connectionState: 'idle', runtimeName: null }),
    )

    confirm = container.querySelector(
      '[data-testid="runtime-detail-op-confirm"]',
    ) as HTMLButtonElement
    expect(confirm.disabled).toBe(true)

    // 即便 click 也不会发请求
    confirm.click()
    await new Promise((r) => setTimeout(r, 30))
    expect(setValue).not.toHaveBeenCalled()
  })

  it('D: connected + lastError 显示真实错误，不显示空参数', () => {
    act(() =>
      useRuntimeStore.setState({
        connectionState: 'connected',
        tagCatalog: [],
        lastError: '加载运行参数失败：HTTP 404',
      }),
    )
    const { container } = render(
      <RuntimeInstanceDetail instanceName="unknown_inst" onBack={() => {}} />,
    )
    expect(container.textContent).toContain('加载运行参数失败：HTTP 404')
    expect(container.textContent).not.toContain('当前实例没有可用参数')
  })
})
