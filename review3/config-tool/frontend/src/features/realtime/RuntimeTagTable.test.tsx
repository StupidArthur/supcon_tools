import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRuntimeStore } from '../runtime/useRuntimeStore'
import { RuntimeTagTable } from './RuntimeTagTable'

const ROW_HEIGHT = 28
const VIEWPORT_HEIGHT = 384

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
    const tagCatalog = Array.from({ length: TOTAL }, (_, i) => ({
      name: `tag${String(i).padStart(5, '0')}`,
      dataType: 'number' as const,
      writable: true,
      forceable: true,
      display: i < 10,
    }))
    const rawSnapshot: Record<string, number> = {}
    for (let i = 0; i < 30; i++) {
      rawSnapshot[`tag${String(i).padStart(5, '0')}`] = i * 0.1
    }

    act(() => {
      useRuntimeStore.setState({ tagCatalog, rawSnapshot })
    })

    const { container } = render(<RuntimeTagTable />)
    await waitFor(() => {
      expect(container.textContent).toContain(`(${TOTAL})`)
    })
    const rows = container.querySelectorAll('[data-testid="tag-table-row"]')
    expect(rows.length).toBeGreaterThan(0)
    expect(rows.length).toBeLessThan(100)
    expect(rows[0].getAttribute('data-tag-name')).toBe('tag00000')
  })

  it('empty catalog then async load: no hook order crash, shows 100 rows after load', async () => {
    act(() => {
      useRuntimeStore.setState({ tagCatalog: [], rawSnapshot: null })
    })

    const { container } = render(<RuntimeTagTable />)
    expect(container.querySelector('[data-testid="tag-table-empty"]')).toBeTruthy()

    const tagCatalog = Array.from({ length: 100 }, (_, i) => ({
      name: `tag${String(i).padStart(5, '0')}`,
      dataType: 'number' as const,
      writable: true,
      forceable: true,
      display: false,
    }))
    act(() => {
      useRuntimeStore.setState({ tagCatalog })
    })

    await waitFor(() => {
      expect(container.textContent).toContain('(100)')
    })
    const rows = container.querySelectorAll('[data-testid="tag-table-row"]')
    expect(rows.length).toBeGreaterThan(0)
    expect(rows.length).toBeLessThan(100)
    expect(rows[0].getAttribute('data-tag-name')).toBe('tag00000')
  })

  it('scrolling near the bottom keeps absolute row positions and subscribes bottom tags', async () => {
    const TOTAL = 10000
    const tagCatalog = Array.from({ length: TOTAL }, (_, i) => ({
      name: `tag${String(i).padStart(5, '0')}`,
      dataType: 'number' as const,
      writable: true,
      forceable: true,
      display: false,
    }))
    act(() => {
      useRuntimeStore.setState({ tagCatalog, rawSnapshot: null })
    })

    let subscribedTags: string[] = []
    const origRegister = useRuntimeStore.getState().registerSubscription
    act(() => {
      useRuntimeStore.setState({
        registerSubscription: ((source: string, tags: string[] | null) => {
          if (source === 'tagTable' && tags) subscribedTags = tags
          origRegister(source, tags)
        }) as any,
      })
    })

    const { container } = render(<RuntimeTagTable />)
    await waitFor(() => {
      expect(container.textContent).toContain(`(${TOTAL})`)
    })

    const scrollEl = container.querySelector('[data-testid="tag-table-scroll"]')!
    const targetScrollTop = (TOTAL - 20) * ROW_HEIGHT

    act(() => {
      fireEvent.scroll(scrollEl, { target: { scrollTop: targetScrollTop } })
    })
    await waitFor(() => {
      const rows = container.querySelectorAll('[data-testid="tag-table-row"]')
      expect(rows.length).toBeGreaterThan(0)
    })
    await new Promise((r) => setTimeout(r, 150))

    const rows = container.querySelectorAll('[data-testid="tag-table-row"]')
    expect(rows.length).toBeLessThan(100)

    const lastRow = rows[rows.length - 1]
    const lastName = lastRow.getAttribute('data-tag-name')!
    expect(lastName).toMatch(/tag0[0-9]{4}/)

    const topStyle = lastRow.getAttribute('style') || ''
    expect(topStyle).not.toContain('top: 0px')

    const lastTagNum = parseInt(lastName.replace('tag', ''), 10)
    const expectedTop = lastTagNum * ROW_HEIGHT
    expect(topStyle).toContain(`top: ${expectedTop}px`)

    expect(subscribedTags.length).toBeGreaterThan(0)
    const hasBottomTag = subscribedTags.some((t) => {
      const n = parseInt(t.replace('tag', ''), 10)
      return n > TOTAL - 100
    })
    expect(hasBottomTag).toBe(true)
  })

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
    await new Promise((r) => setTimeout(r, 200))
    const initialCount = subscribeCount
    expect(initialCount).toBeGreaterThanOrEqual(1)

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

    await new Promise((r) => setTimeout(r, 200))
    const finalCount = subscribeCount
    expect(finalCount - initialCount).toBeLessThanOrEqual(2)
  })

  it('unmount calls unregisterSubscription for tagTable and force', async () => {
    const catalog = Array.from({ length: 5 }, (_, i) => ({
      name: `tag${i}`,
      dataType: 'number' as const,
      writable: true,
      forceable: true,
      display: false,
    }))
    act(() => {
      useRuntimeStore.setState({ tagCatalog: catalog })
    })

    const unregistered: string[] = []
    const origUnregister = useRuntimeStore.getState().unregisterSubscription
    act(() => {
      useRuntimeStore.setState({
        unregisterSubscription: ((source: string) => {
          unregistered.push(source)
          origUnregister(source)
        }) as any,
      })
    })

    const { unmount } = render(<RuntimeTagTable />)
    await new Promise((r) => setTimeout(r, 50))

    unmount()
    await new Promise((r) => setTimeout(r, 50))

    expect(unregistered).toContain('tagTable')
    expect(unregistered).toContain('force')
  })
})
