/**
 * Stage 3 reviewer acceptance: RuntimeToolbar state machine and running identity.
 * WebSocket/runtime transport is mocked — stage 4 owns WS contract tests.
 */
import { act, fireEvent, render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RuntimeToolbar } from '../../src/features/templates/RuntimeToolbar'
import { useTemplateStore } from '../../src/features/templates/useTemplateStore'
import { useCanvasStore } from '../../src/store/useCanvasStore'
import { systemApi, templateApi } from '../../src/lib/api'

vi.mock('../../src/features/templates/useTemplateStore', () => ({
  useTemplateStore: vi.fn(),
}))
vi.mock('../../src/store/useCanvasStore', () => ({
  useCanvasStore: vi.fn(),
}))
vi.mock('../../src/lib/api', () => ({
  systemApi: {
    saveYAMLFile: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
    status: vi.fn(),
  },
  templateApi: { isBuiltin: vi.fn() },
}))
vi.mock('../../src/features/runtime/useRuntimeStore', () => ({
  useRuntimeStore: vi.fn((selector: (s: RuntimeStoreMock) => unknown) =>
    selector(runtimeStoreMock),
  ),
}))

interface RuntimeStoreMock {
  connectionState: string
  stale: boolean
  runtimeName: string | null
  apiHost: string
  apiPort: number
  connect: ReturnType<typeof vi.fn>
  disconnect: ReturnType<typeof vi.fn>
}

const mockRuntimeConnect = vi.fn().mockResolvedValue(undefined)
const mockRuntimeDisconnect = vi.fn()

const runtimeStoreMock: RuntimeStoreMock = {
  connectionState: 'idle',
  stale: false,
  runtimeName: null,
  apiHost: '127.0.0.1',
  apiPort: 8000,
  connect: mockRuntimeConnect,
  disconnect: mockRuntimeDisconnect,
}

describe('stage 3 runtime toolbar state acceptance', () => {
  const mockSave = vi.fn()
  const mockReset = vi.fn()
  const mockSetView = vi.fn()
  const mockSetRuntimeState = vi.fn()
  const mockSetRunningIdentity = vi.fn()

  const defaultState = {
    templateId: 'second_order_tank' as const,
    definition: {
      id: 'second_order_tank' as const,
      displayName: '单阀门二阶水箱',
      defaultBuiltinPath: 'config/单阀门二阶水箱.yaml',
      programs: [],
    },
    sourcePath: 'config/单阀门二阶水箱.yaml',
    savedContentHash: 'abc123',
    draft: { cycleTime: 0.5 },
    dirtyPaths: new Set<string>(),
    runtimeState: 'STOPPED_EDITING' as const,
    validationErrors: [],
    save: mockSave,
    reset: mockReset,
    setRuntimeState: mockSetRuntimeState,
    setRunningIdentity: mockSetRunningIdentity,
  }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useCanvasStore).mockImplementation((selector: (s: { setView: typeof mockSetView }) => unknown) =>
      selector({ setView: mockSetView }),
    )
    vi.mocked(templateApi.isBuiltin).mockResolvedValue(false)
    vi.mocked(systemApi.saveYAMLFile).mockResolvedValue('G:/repo/config/user-scheme.yaml')
    vi.mocked(systemApi.start).mockResolvedValue(undefined)
    vi.mocked(systemApi.stop).mockResolvedValue(undefined)
    vi.mocked(systemApi.status).mockResolvedValue({
      running: true,
      apiReady: true,
      configPath: 'config/单阀门二阶水箱.yaml',
      configHash: 'abc123',
      startedAt: '2026-07-20T12:00:00Z',
    })
    vi.mocked(useTemplateStore).mockImplementation((selector: (s: typeof defaultState) => unknown) => {
      if (typeof selector === 'function') {
        return selector(defaultState)
      }
      return defaultState
    })
    vi.mocked(useTemplateStore).getState = vi.fn().mockReturnValue(defaultState)
    mockRuntimeConnect.mockResolvedValue(undefined)
  })

  it('shows STOPPED_EDITING preview label before start', () => {
    const { container } = render(<RuntimeToolbar />)
    expect(container.textContent).toContain('组态预览')
  })

  it('transitions STOPPED_EDITING → STARTING → SIMULATION_RUNNING on successful start', async () => {
    const { container } = render(<RuntimeToolbar />)
    fireEvent.click(container.querySelector('[data-testid="start-button"]')!)

    await waitFor(() => expect(mockSetRuntimeState).toHaveBeenCalledWith('STARTING'))
    await waitFor(() => expect(systemApi.start).toHaveBeenCalled())
    await waitFor(() => expect(mockSetRuntimeState).toHaveBeenCalledWith('SIMULATION_RUNNING'))
  })

  it('does not show SIMULATION_RUNNING before start promise resolves', async () => {
    let resolveStart!: () => void
    const pending = new Promise<void>((resolve) => {
      resolveStart = resolve
    })
    vi.mocked(systemApi.start).mockReturnValue(pending)

    const { container } = render(<RuntimeToolbar />)
    fireEvent.click(container.querySelector('[data-testid="start-button"]')!)

    await waitFor(() => expect(mockSetRuntimeState).toHaveBeenCalledWith('STARTING'))
    expect(mockSetRuntimeState).not.toHaveBeenCalledWith('SIMULATION_RUNNING')
    expect(container.textContent).not.toContain('仿真运行中')

    await act(async () => {
      resolveStart()
      await pending
    })
    await waitFor(() => expect(mockSetRuntimeState).toHaveBeenCalledWith('SIMULATION_RUNNING'))
  })

  it('STARTING → ERROR when start fails', async () => {
    vi.mocked(systemApi.start).mockRejectedValue(new Error('进程提前退出'))
    const { container } = render(<RuntimeToolbar />)
    fireEvent.click(container.querySelector('[data-testid="start-button"]')!)

    await waitFor(() => expect(mockSetRuntimeState).toHaveBeenCalledWith('ERROR'))
    await waitFor(() => expect(mockSetRunningIdentity).toHaveBeenCalledWith(null))
    expect(container.querySelector('[data-testid="start-error"]')).toBeTruthy()
  })

  it('SIMULATION_RUNNING → STOPPING → STOPPED_EDITING on stop', async () => {
    const stateRunning = { ...defaultState, runtimeState: 'SIMULATION_RUNNING' as const }
    vi.mocked(useTemplateStore).mockImplementation((selector: (s: typeof stateRunning) => unknown) =>
      selector(stateRunning),
    )

    const { container } = render(<RuntimeToolbar />)
    fireEvent.click(container.querySelector('[data-testid="stop-button"]')!)

    await waitFor(() => expect(mockSetRuntimeState).toHaveBeenCalledWith('STOPPING'))
    await waitFor(() => expect(mockRuntimeDisconnect).toHaveBeenCalled())
    await waitFor(() => expect(systemApi.stop).toHaveBeenCalled())
    await waitFor(() => expect(mockSetRuntimeState).toHaveBeenCalledWith('STOPPED_EDITING'))
    await waitFor(() => expect(mockSetRunningIdentity).toHaveBeenCalledWith(null))
  })

  it('requires save before start when dirty', async () => {
    const dirtyState = { ...defaultState, dirtyPaths: new Set(['tank2.height']) }
    vi.mocked(useTemplateStore).mockImplementation((selector: (s: typeof dirtyState) => unknown) =>
      selector(dirtyState),
    )
    vi.mocked(useTemplateStore).getState = vi.fn().mockReturnValue(dirtyState)

    const { container } = render(<RuntimeToolbar />)
    fireEvent.click(container.querySelector('[data-testid="start-button"]')!)

    await waitFor(() => expect(mockSave).toHaveBeenCalled())
    await waitFor(() => expect(systemApi.start).toHaveBeenCalled())
  })

  it('does not start when save fails', async () => {
    const dirtyState = { ...defaultState, dirtyPaths: new Set(['tank2.height']) }
    vi.mocked(useTemplateStore).mockImplementation((selector: (s: typeof dirtyState) => unknown) =>
      selector(dirtyState),
    )
    mockSave.mockRejectedValue(new Error('保存失败'))

    const { container } = render(<RuntimeToolbar />)
    fireEvent.click(container.querySelector('[data-testid="start-button"]')!)

    await waitFor(() => expect(mockSave).toHaveBeenCalled())
    expect(systemApi.start).not.toHaveBeenCalled()
  })

  it('late start promise must not restore running state after stop during STARTING', async () => {
    let currentState: typeof defaultState = { ...defaultState }
    vi.mocked(useTemplateStore).mockImplementation((selector: (s: typeof defaultState) => unknown) =>
      selector(currentState),
    )
    vi.mocked(useTemplateStore).getState = vi.fn().mockImplementation(() => currentState)

    let resolveStart!: () => void
    const startPromise = new Promise<void>((resolve) => {
      resolveStart = resolve
    })
    vi.mocked(systemApi.start).mockReturnValue(startPromise)

    const { container, rerender } = render(<RuntimeToolbar />)
    fireEvent.click(container.querySelector('[data-testid="start-button"]')!)
    await waitFor(() => expect(systemApi.start).toHaveBeenCalled())

    currentState = { ...currentState, runtimeState: 'STARTING' }
    rerender(<RuntimeToolbar />)
    fireEvent.click(container.querySelector('[data-testid="stop-button"]')!)
    await waitFor(() => expect(systemApi.stop).toHaveBeenCalled())
    await waitFor(() => expect(mockSetRuntimeState).toHaveBeenCalledWith('STOPPED_EDITING'))

    await act(async () => {
      resolveStart()
      await startPromise
    })

    expect(systemApi.status).not.toHaveBeenCalled()
    expect(mockSetRuntimeState).not.toHaveBeenCalledWith('SIMULATION_RUNNING')
    expect(mockSetRuntimeState).not.toHaveBeenCalledWith('ERROR')
  })

  it('running identity path hash startedAt comes only from backend status', async () => {
    vi.mocked(systemApi.status).mockResolvedValue({
      running: true,
      apiReady: true,
      configPath: 'G:/repo/config/from-backend.yaml',
      configHash: 'backendhash456',
      startedAt: '2026-07-20T12:00:00Z',
    })

    const { container } = render(<RuntimeToolbar />)
    fireEvent.click(container.querySelector('[data-testid="start-button"]')!)

    await waitFor(() =>
      expect(mockSetRunningIdentity).toHaveBeenCalledWith({
        path: 'G:/repo/config/from-backend.yaml',
        contentHash: 'backendhash456',
        startedAt: '2026-07-20T12:00:00Z',
      }),
    )
  })

  it('disconnects runtime transport when leaving page while running', async () => {
    const stateRunning = { ...defaultState, runtimeState: 'SIMULATION_RUNNING' as const }
    vi.mocked(useTemplateStore).mockImplementation((selector: (s: typeof stateRunning) => unknown) =>
      selector(stateRunning),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    const { container } = render(<RuntimeToolbar />)
    fireEvent.click(container.querySelector('[data-testid="back-button"]')!)

    await waitFor(() => expect(mockRuntimeDisconnect).toHaveBeenCalled())
    await waitFor(() => expect(systemApi.stop).toHaveBeenCalled())
  })

  it('does not treat WebSocket connect failure as stage-3 completion gate', async () => {
    mockRuntimeConnect.mockRejectedValue(new Error('ws unavailable'))
    const { container } = render(<RuntimeToolbar />)
    fireEvent.click(container.querySelector('[data-testid="start-button"]')!)

    await waitFor(() => expect(mockSetRuntimeState).toHaveBeenCalledWith('SIMULATION_RUNNING'))
    expect(mockRuntimeConnect).toHaveBeenCalled()
  })
})
