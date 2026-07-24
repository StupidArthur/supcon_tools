import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRuntimeStore } from '../runtime/useRuntimeStore'
import { RuntimeTagTable } from './RuntimeTagTable'

// 验证：位号表用 tagCatalog 作行源，不会被过滤 snapshot 自我收缩。
// 场景：10000 个 tag catalog，初始只看到前 30 个，但表行总数保持 10000。
describe('RuntimeTagTable catalog-driven subscription', () => {
  beforeEach(() => {
    useRuntimeStore.getState()._reset()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    cleanup()
    useRuntimeStore.getState()._reset()
    vi.restoreAllMocks()
  })

  it('10000-tag catalog: row count = catalog size, value lookup falls back to snapshot', async () => {
    const TOTAL = 10000
    // 构造 catalog：10000 个 numeric tag
    const tagCatalog = Array.from({ length: TOTAL }, (_, i) => ({
      name: `tag${String(i).padStart(5, '0')}`,
      dataType: 'number' as const,
      writable: true,
      forceable: true,
      display: i < 10,
    }))
    // rawSnapshot 只含 30 个被订阅 tag 的值（订阅模式行为模拟）
    const rawSnapshot: Record<string, number> = {}
    for (let i = 0; i < 30; i++) {
      rawSnapshot[`tag${String(i).padStart(5, '0')}`] = i * 0.1
    }

    act(() => {
      useRuntimeStore.setState({ tagCatalog, rawSnapshot })
    })

    const { container } = render(<RuntimeTagTable />)
    await waitFor(() => {
      // 表头应显示 10000 行
      expect(container.textContent).toContain(`(${TOTAL})`)
    })
    // DOM 中渲染的行：visibleTags 数量（不展开全部 10000）
    const rows = container.querySelectorAll('[data-testid="tag-table-row"]')
    expect(rows.length).toBeGreaterThan(0)
    expect(rows.length).toBeLessThan(100)
    // 第一个可见行是 tag00000
    expect(rows[0].getAttribute('data-tag-name')).toBe('tag00000')
  })

  it('滚动到底部：应能通过搜索框定位 tag09999（即便订阅模式 rawSnapshot 不含该值）', async () => {
    const TOTAL = 10000
    const tagCatalog = Array.from({ length: TOTAL }, (_, i) => ({
      name: `tag${String(i).padStart(5, '0')}`,
      dataType: 'number' as const,
      writable: true,
      forceable: true,
      display: false,
    }))
    // rawSnapshot 只含前 30 个 tag（订阅模式）
    const rawSnapshot: Record<string, number> = {}
    for (let i = 0; i < 30; i++) {
      rawSnapshot[`tag${String(i).padStart(5, '0')}`] = i
    }

    act(() => {
      useRuntimeStore.setState({ tagCatalog, rawSnapshot })
    })

    const { container } = render(<RuntimeTagTable />)
    const filterInput = container.querySelector('input[placeholder*="搜索"]') as HTMLInputElement
    expect(filterInput).toBeTruthy()
    // tag09999 搜索
    act(() => {
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )?.set
      nativeInputValueSetter?.call(filterInput, '09999')
      filterInput.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await waitFor(() => {
      expect(container.textContent).toContain('(1)')
    })
    // tag09999 必须出现在 DOM 中（catalog 驱动）
    const row = container.querySelector('[data-testid="tag-table-row"]')
    expect(row?.getAttribute('data-tag-name')).toBe('tag09999')
    // 值应是 '—'（因为 rawSnapshot 不含 tag09999）
    expect(row?.textContent).toContain('—')
  })

  // 阶段 5-4 收口：高频 snapshot（20Hz × 200ms）不应持续重置 debounce。
  // 关键：visibleNames 不依赖 latestFrame/rawSnapshot，所以 latestFrame
  // 引用变化时 visibleNames 引用不变 → React 不重渲染 effect → debounce 完成。
  it('高频 snapshot 不会持续重置 100ms debounce', async () => {
    const catalog = Array.from({ length: 100 }, (_, i) => ({
      name: `tag${i}`,
      dataType: 'number' as const,
      writable: true,
      forceable: true,
      display: false,
    }))
    act(() => {
      useRuntimeStore.setState({ tagCatalog: catalog, rawSnapshot: undefined, latestFrame: undefined })
    })

    // 模拟 createRuntimeWs.setSubscription 被调用：用 store action 计数
    let subscribeCount = 0
    const originalRegister = useRuntimeStore.getState().registerSubscription
    const countingRegister = (source: string, tags: string[] | null) => {
      if (source === 'tagTable') subscribeCount += 1
      originalRegister(source, tags)
    }
    act(() => {
      useRuntimeStore.setState({ registerSubscription: countingRegister as any })
    })

    render(<RuntimeTagTable />)
    // 等待首次 debounce 完成（100ms + 缓冲）
    await new Promise((r) => setTimeout(r, 200))
    const initialCount = subscribeCount
    expect(initialCount).toBeGreaterThanOrEqual(1)

    // 推送 20 次高频 snapshot（每 10ms 一次）
    for (let i = 0; i < 20; i++) {
      act(() => {
        useRuntimeStore.setState({
          latestFrame: {
            values: Object.fromEntries(
              catalog.map((t, idx) => [t.name, (i + idx) * 0.1]),
            ),
            receivedAt: Date.now() + i,
            cycleCount: i,
            simTime: i * 0.5,
          } as any,
        })
      })
      await new Promise((r) => setTimeout(r, 10))
    }

    // 等 debounce 收敛（100ms + 缓冲）
    await new Promise((r) => setTimeout(r, 200))
    const finalCount = subscribeCount
    // 高频 snapshot 期间：subscribeCount 只在 visibleNames 变化时 +1。
    // visibleNames 在没滚动 / 没 filter 时不变 → subscribeCount 在此期间
    // 不应有显著增长（最多 +1 收尾）。如果旧实现：visibleNames 包含
    // 包含 latestFrame 引用 → 每次 snapshot 都触发 effect → 持续 +1。
    expect(finalCount - initialCount).toBeLessThanOrEqual(2)
  })
})
