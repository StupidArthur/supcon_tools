import { act, cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRuntimeStore } from '../runtime/useRuntimeStore'
import { useRealtimeRunSessionStore } from './useRealtimeRunSessionStore'
import { DashboardPage } from './DashboardPage'

describe('DashboardPage session identity gating', () => {
  const PROJECT_ID = 'proj-abc'

  beforeEach(() => {
    useRuntimeStore.getState()._reset()
    useRealtimeRunSessionStore.setState({ session: null })
    vi.restoreAllMocks()
  })

  afterEach(() => {
    cleanup()
    useRuntimeStore.getState()._reset()
    useRealtimeRunSessionStore.setState({ session: null })
    vi.restoreAllMocks()
  })

  it('same project session: registers dashboard subscription, edit enabled', async () => {
    useRealtimeRunSessionStore.setState({
      session: {
        sessionId: 's1',
        sourceKind: 'project',
        projectId: PROJECT_ID,
        projectName: 'TestProject',
        runtimeRevision: 'r1',
        compiledConfigPath: '/tmp/c.yaml',
        configHash: 'h1',
        runtimeName: 'rt1',
        cycleTime: 0.5,
        opcUaPort: 18000,
        apiHost: '127.0.0.1',
        apiPort: 8000,
        startedAt: '2026-01-01T00:00:00Z',
        state: 'running',
      },
    })

    let registeredTags: string[] | null = null
    const origRegister = useRuntimeStore.getState().registerSubscription
    act(() => {
      useRuntimeStore.setState({
        registerSubscription: ((source: string, tags: string[] | null) => {
          if (source === 'dashboard') registeredTags = tags
          origRegister(source, tags)
        }) as any,
      })
    })

    render(<DashboardPage projectId={PROJECT_ID} />)
    await new Promise((r) => setTimeout(r, 100))

    expect(registeredTags).toEqual([])

    const editBtn = document.querySelector('[data-testid="dashboard-edit-toggle"]') as HTMLButtonElement
    expect(editBtn.disabled).toBe(false)
  })

  it('different project session: unregisters dashboard, edit disabled, shows mismatch', async () => {
    useRealtimeRunSessionStore.setState({
      session: {
        sessionId: 's2',
        sourceKind: 'project',
        projectId: 'proj-other',
        projectName: 'OtherProject',
        runtimeRevision: 'r2',
        compiledConfigPath: '/tmp/c2.yaml',
        configHash: 'h2',
        runtimeName: 'rt2',
        cycleTime: 0.5,
        opcUaPort: 18001,
        apiHost: '127.0.0.1',
        apiPort: 8001,
        startedAt: '2026-01-01T01:00:00Z',
        state: 'running',
      },
    })

    let unregistered = false
    const origUnregister = useRuntimeStore.getState().unregisterSubscription
    act(() => {
      useRuntimeStore.setState({
        unregisterSubscription: ((source: string) => {
          if (source === 'dashboard') unregistered = true
          origUnregister(source)
        }) as any,
      })
    })

    render(<DashboardPage projectId={PROJECT_ID} />)
    await new Promise((r) => setTimeout(r, 100))

    expect(unregistered).toBe(true)

    const editBtn = document.querySelector('[data-testid="dashboard-edit-toggle"]') as HTMLButtonElement
    expect(editBtn.disabled).toBe(true)

    expect(document.querySelector('.text-amber-700')?.textContent).toContain('与画面所属项目不匹配')
  })

  it('single-YAML session: no dashboard subscription, edit disabled, shows single-YAML message', async () => {
    useRealtimeRunSessionStore.setState({
      session: {
        sessionId: 's3',
        sourceKind: 'single-yaml',
        sourcePath: '/tmp/config.yaml',
        runtimeRevision: 'r3',
        compiledConfigPath: '/tmp/c3.yaml',
        configHash: 'h3',
        runtimeName: 'rt3',
        cycleTime: 0.5,
        opcUaPort: 18002,
        apiHost: '127.0.0.1',
        apiPort: 8002,
        startedAt: '2026-01-01T02:00:00Z',
        state: 'running',
      },
    })

    let unregistered = false
    const origUnregister = useRuntimeStore.getState().unregisterSubscription
    act(() => {
      useRuntimeStore.setState({
        unregisterSubscription: ((source: string) => {
          if (source === 'dashboard') unregistered = true
          origUnregister(source)
        }) as any,
      })
    })

    render(<DashboardPage projectId={PROJECT_ID} />)
    await new Promise((r) => setTimeout(r, 100))

    expect(unregistered).toBe(true)

    const editBtn = document.querySelector('[data-testid="dashboard-edit-toggle"]') as HTMLButtonElement
    expect(editBtn.disabled).toBe(true)

    expect(document.querySelector('.text-amber-700')?.textContent).toContain('单 YAML')
  })

  it('no session: no dashboard subscription registered, edit enabled, no mismatch message', async () => {
    useRealtimeRunSessionStore.setState({ session: null })

    let registeredTags: string[] | null = undefined as any
    let unregistered = false
    const origRegister = useRuntimeStore.getState().registerSubscription
    const origUnregister = useRuntimeStore.getState().unregisterSubscription
    act(() => {
      useRuntimeStore.setState({
        registerSubscription: ((source: string, tags: string[] | null) => {
          if (source === 'dashboard') registeredTags = tags
          origRegister(source, tags)
        }) as any,
        unregisterSubscription: ((source: string) => {
          if (source === 'dashboard') unregistered = true
          origUnregister(source)
        }) as any,
      })
    })

    render(<DashboardPage projectId={PROJECT_ID} />)
    await new Promise((r) => setTimeout(r, 100))

    expect(registeredTags).toBeUndefined()
    expect(unregistered).toBe(true)

    const editBtn = document.querySelector('[data-testid="dashboard-edit-toggle"]') as HTMLButtonElement
    expect(editBtn.disabled).toBe(false)

    expect(document.querySelector('.text-amber-700')).toBeNull()
  })
})
