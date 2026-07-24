import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRuntimeStore } from '../runtime/useRuntimeStore'
import { RuntimeTagTable } from './RuntimeTagTable'

const ROW_HEIGHT = 28
const VIEWPORT_HEIGHT = 384
const OVERSCAN = 8
const TOTAL_TAGS = 50000

describe('RuntimeTagTable 50k scale', () => {
  beforeEach(() => {
    useRuntimeStore.getState()._reset()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    cleanup()
    useRuntimeStore.getState()._reset()
    vi.restoreAllMocks()
  })

  it('50k catalog: bounded DOM, bounded subscription, no full payload, absolute top', async () => {
    const tagCatalog = Array.from({ length: TOTAL_TAGS }, (_, i) => ({
      name: `tag${String(i).padStart(5, '0')}`,
      dataType: 'number' as const,
      writable: true,
      forceable: false,
      display: false,
    }))

    act(() => {
      useRuntimeStore.setState({ tagCatalog, rawSnapshot: null })
    })

    let lastSubscribedTags: string[] | null = null
    let subscribeCount = 0
    const origRegister = useRuntimeStore.getState().registerSubscription
    act(() => {
      useRuntimeStore.setState({
        registerSubscription: ((source: string, tags: string[] | null) => {
          if (source === 'tagTable') {
            subscribeCount += 1
            lastSubscribedTags = tags
          }
          origRegister(source, tags)
        }) as any,
      })
    })

    const t0 = performance.now()
    const { container } = render(<RuntimeTagTable />)
    await waitFor(() => {
      expect(container.textContent).toContain(`(${TOTAL_TAGS})`)
    })
    await new Promise((r) => setTimeout(r, 150))
    const renderDuration = performance.now() - t0

    const rows = container.querySelectorAll('[data-testid="tag-table-row"]')
    expect(rows.length).toBeGreaterThan(0)
    expect(rows.length).toBeLessThan(100)

    await new Promise((r) => setTimeout(r, 150))
    expect(lastSubscribedTags).not.toBeNull()
    expect(lastSubscribedTags!.length).toBeLessThan(100)
    expect(lastSubscribedTags!.length).toBeGreaterThan(0)

    expect(lastSubscribedTags!.length).toBeLessThan(TOTAL_TAGS)

    await new Promise((r) => setTimeout(r, 150))
    const initialSubCount = subscribeCount

    const scrollEl = container.querySelector('[data-testid="tag-table-scroll"]')!
    const targetTop = (TOTAL_TAGS - 20) * ROW_HEIGHT

    const t1 = performance.now()
    act(() => {
      fireEvent.scroll(scrollEl, { target: { scrollTop: targetTop } })
    })
    await waitFor(() => {
      const r = container.querySelectorAll('[data-testid="tag-table-row"]')
      expect(r.length).toBeGreaterThan(0)
    })
    await new Promise((r) => setTimeout(r, 150))
    const scrollDuration = performance.now() - t1

    const bottomRows = container.querySelectorAll('[data-testid="tag-table-row"]')
    expect(bottomRows.length).toBeLessThan(100)

    const lastRow = bottomRows[bottomRows.length - 1]
    const lastName = lastRow.getAttribute('data-tag-name')!
    const lastNum = parseInt(lastName.replace('tag', ''), 10)
    expect(lastNum).toBeGreaterThan(TOTAL_TAGS - 100)

    const topStyle = lastRow.getAttribute('style') || ''
    const expectedTop = lastNum * ROW_HEIGHT
    expect(topStyle).toContain(`top: ${expectedTop}px`)

    const t2 = performance.now()
    for (let i = 0; i < 30; i++) {
      act(() => {
        useRuntimeStore.setState({
          latestFrame: {
            values: Object.fromEntries(
              tagCatalog.slice(0, 50).map((t, idx) => [t.name, (i + idx) * 0.1]),
            ),
            receivedAt: Date.now() + i,
            cycleCount: i,
            simTime: i * 0.5,
          } as any,
        })
      })
      await new Promise((r) => setTimeout(r, 10))
    }
    await new Promise((r) => setTimeout(r, 150))
    const snapshotDuration = performance.now() - t2

    const finalSubCount = subscribeCount
    expect(finalSubCount - initialSubCount).toBeLessThanOrEqual(2)

    const subTagsAfterSnap = lastSubscribedTags!
    expect(subTagsAfterSnap.length).toBeLessThan(100)

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

    cleanup()

    console.log(
      `SCALE_RESULT catalog=${TOTAL_TAGS} domRows=${rows.length} subscribed=${lastSubscribedTags!.length} ` +
      `renderMs=${renderDuration.toFixed(0)} scrollMs=${scrollDuration.toFixed(0)} snapshotMs=${snapshotDuration.toFixed(0)}`,
    )

    expect(renderDuration).toBeLessThan(15000)
    expect(scrollDuration).toBeLessThan(15000)
    expect(snapshotDuration).toBeLessThan(15000)

    expect(unregistered).toContain('tagTable')
    expect(unregistered).toContain('force')
  })
})
