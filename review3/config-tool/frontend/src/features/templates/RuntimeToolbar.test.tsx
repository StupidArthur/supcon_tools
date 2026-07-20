import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, fireEvent, waitFor } from '@testing-library/react'
import { RuntimeToolbar } from './RuntimeToolbar'
import { useTemplateStore } from './useTemplateStore'
import { systemApi, templateApi } from '../../lib/api'
import { useCanvasStore } from '../../store/useCanvasStore'

// Mock useTemplateStore
vi.mock('./useTemplateStore', () => ({
  useTemplateStore: vi.fn(),
}))
vi.mock('../../store/useCanvasStore', () => ({
  useCanvasStore: vi.fn(),
}))
vi.mock('../../lib/api', () => ({
  systemApi: {
    saveYAMLFile: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
    status: vi.fn(),
  },
  templateApi: { isBuiltin: vi.fn() },
}))

describe('RuntimeToolbar', () => {
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
    vi.mocked(useCanvasStore).mockImplementation((selector: any) => selector({ setView: mockSetView }))
    vi.mocked(templateApi.isBuiltin).mockResolvedValue(false)
    vi.mocked(systemApi.saveYAMLFile).mockResolvedValue('G:/repo/config/user-scheme.yaml')
    vi.mocked(systemApi.start).mockResolvedValue(undefined)
    vi.mocked(systemApi.stop).mockResolvedValue(undefined)
    vi.mocked(systemApi.status).mockResolvedValue({
      running: true,
      apiReady: true,
      configPath: 'config/单阀门二阶水箱.yaml',
      configHash: 'abc123',
      startedAt: '2026-07-19T12:00:00Z',
    })
    // 默认返回 defaultState
    vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
      if (typeof selector === 'function') {
        return selector(defaultState)
      }
      return defaultState
    })
    // Mock getState
    vi.mocked(useTemplateStore).getState = vi.fn().mockReturnValue(defaultState)
  })

  it('应渲染工具栏', () => {
    const { container } = render(<RuntimeToolbar />)
    expect(container.querySelector('[data-testid="runtime-toolbar"]')).toBeTruthy()
  })

  it('应显示模板名称', () => {
    const { container } = render(<RuntimeToolbar />)
    expect(container.textContent).toContain('单阀门二阶水箱')
  })

  it('应显示文件路径', () => {
    const { container } = render(<RuntimeToolbar />)
    expect(container.textContent).toContain('config/单阀门二阶水箱.yaml')
  })

  it('应显示组态预览状态', () => {
    const { container } = render(<RuntimeToolbar />)
    expect(container.textContent).toContain('组态预览')
  })

  it('应显示保存按钮（禁用状态，无 dirty）', () => {
    const { container } = render(<RuntimeToolbar />)
    const saveButton = container.querySelector('[data-testid="save-button"]')
    expect(saveButton).toBeTruthy()
    expect(saveButton).toHaveProperty('disabled', true)
  })

  it('应显示保存按钮（启用状态，有 dirty）', () => {
    const stateWithDirty = {
      ...defaultState,
      dirtyPaths: new Set(['tank2.height']),
    }
    vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
      if (typeof selector === 'function') {
        return selector(stateWithDirty)
      }
      return stateWithDirty
    })

    const { container } = render(<RuntimeToolbar />)
    const saveButton = container.querySelector('[data-testid="save-button"]')
    expect(saveButton).toHaveProperty('disabled', false)
  })

  it('应显示 dirty 标记', () => {
    const stateWithDirty = {
      ...defaultState,
      dirtyPaths: new Set(['tank2.height', 'pid.SV']),
    }
    vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
      if (typeof selector === 'function') {
        return selector(stateWithDirty)
      }
      return stateWithDirty
    })

    const { container } = render(<RuntimeToolbar />)
    expect(container.textContent).toContain('未保存 2 处')
  })

  it('点击保存应调用 save', async () => {
    const stateWithDirty = {
      ...defaultState,
      dirtyPaths: new Set(['tank2.height']),
    }
    vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
      if (typeof selector === 'function') {
        return selector(stateWithDirty)
      }
      return stateWithDirty
    })

    const { container } = render(<RuntimeToolbar />)
    const saveButton = container.querySelector('[data-testid="save-button"]')
    fireEvent.click(saveButton!)

    await waitFor(() => expect(mockSave).toHaveBeenCalled())
  })

  it('有校验错误时保存按钮应禁用', () => {
    const stateWithErrors = {
      ...defaultState,
      dirtyPaths: new Set(['tank2.height']),
      validationErrors: [{ path: 'tank2.height', level: 'error' as const, message: '高度必须大于 0' }],
    }
    vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
      if (typeof selector === 'function') {
        return selector(stateWithErrors)
      }
      return stateWithErrors
    })

    const { container } = render(<RuntimeToolbar />)
    const saveButton = container.querySelector('[data-testid="save-button"]')
    expect(saveButton).toHaveProperty('disabled', true)
  })

  it('点击返回应调用 reset（无 dirty）', async () => {
    // Mock window.confirm
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    const { container } = render(<RuntimeToolbar />)
    const backButton = container.querySelector('[data-testid="back-button"]')
    fireEvent.click(backButton!)

    await waitFor(() => expect(mockReset).toHaveBeenCalled())
    confirmSpy.mockRestore()
  })

  it('有 dirty 时点击返回应确认', () => {
    const stateWithDirty = {
      ...defaultState,
      dirtyPaths: new Set(['tank2.height']),
    }
    vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
      if (typeof selector === 'function') {
        return selector(stateWithDirty)
      }
      return stateWithDirty
    })

    // Mock window.confirm 返回 false
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)

    const { container } = render(<RuntimeToolbar />)
    const backButton = container.querySelector('[data-testid="back-button"]')
    fireEvent.click(backButton!)

    expect(mockReset).not.toHaveBeenCalled()
    expect(confirmSpy).toHaveBeenCalledWith('有未保存的修改，确定要离开吗？')
    confirmSpy.mockRestore()
  })

  it('应显示另存为按钮', () => {
    const { container } = render(<RuntimeToolbar />)
    expect(container.querySelector('[data-testid="save-as-button"]')).toBeTruthy()
  })

  it('另存为必须选择新路径并传给 store', async () => {
    const stateWithDirty = { ...defaultState, dirtyPaths: new Set(['tank2.height']) }
    vi.mocked(useTemplateStore).mockImplementation((selector: any) => selector(stateWithDirty))
    const { container } = render(<RuntimeToolbar />)

    fireEvent.click(container.querySelector('[data-testid="save-as-button"]')!)

    await waitFor(() => expect(mockSave).toHaveBeenCalledWith({
      targetPath: 'G:/repo/config/user-scheme.yaml',
      allowOverwrite: true,
    }))
  })

  it('取消另存为时不得保存', async () => {
    vi.mocked(systemApi.saveYAMLFile).mockResolvedValue('')
    const { container } = render(<RuntimeToolbar />)

    fireEvent.click(container.querySelector('[data-testid="save-as-button"]')!)

    await waitFor(() => expect(systemApi.saveYAMLFile).toHaveBeenCalled())
    expect(mockSave).not.toHaveBeenCalled()
  })

  it('内置模板首次保存必须转入另存为', async () => {
    const stateWithDirty = { ...defaultState, dirtyPaths: new Set(['tank2.height']) }
    vi.mocked(useTemplateStore).mockImplementation((selector: any) => selector(stateWithDirty))
    vi.mocked(templateApi.isBuiltin).mockResolvedValue(true)
    const { container } = render(<RuntimeToolbar />)

    fireEvent.click(container.querySelector('[data-testid="save-button"]')!)

    await waitFor(() => expect(mockSave).toHaveBeenCalledWith({
      targetPath: 'G:/repo/config/user-scheme.yaml',
      allowOverwrite: true,
    }))
    expect(mockSave).toHaveBeenCalledTimes(1)
  })

  it('应显示高级视图按钮', () => {
    const { container } = render(<RuntimeToolbar />)
    expect(container.querySelector('[data-testid="advanced-view-button"]')).toBeTruthy()
  })

  it('点击高级视图应进入现有高级组态', () => {
    const { container } = render(<RuntimeToolbar />)
    fireEvent.click(container.querySelector('[data-testid="advanced-view-button"]')!)
    expect(mockSetView).toHaveBeenCalledWith('config')
  })

  it('应显示启动中状态', () => {
    const stateStarting = {
      ...defaultState,
      runtimeState: 'STARTING' as const,
    }
    vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
      if (typeof selector === 'function') {
        return selector(stateStarting)
      }
      return stateStarting
    })

    const { container } = render(<RuntimeToolbar />)
    expect(container.textContent).toContain('启动中...')
  })

  it('应显示仿真运行中状态', () => {
    const stateRunning = {
      ...defaultState,
      runtimeState: 'SIMULATION_RUNNING' as const,
    }
    vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
      if (typeof selector === 'function') {
        return selector(stateRunning)
      }
      return stateRunning
    })

    const { container } = render(<RuntimeToolbar />)
    expect(container.textContent).toContain('仿真运行中')
  })

  it('应显示错误状态', () => {
    const stateError = {
      ...defaultState,
      runtimeState: 'ERROR' as const,
    }
    vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
      if (typeof selector === 'function') {
        return selector(stateError)
      }
      return stateError
    })

    const { container } = render(<RuntimeToolbar />)
    expect(container.textContent).toContain('错误')
  })

  it('不应渲染（templateId 不匹配）', () => {
    const stateNull = {
      ...defaultState,
      templateId: null,
    }
    vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
      if (typeof selector === 'function') {
        return selector(stateNull)
      }
      return stateNull
    })

    const { container } = render(<RuntimeToolbar />)
    expect(container.firstChild).toBeNull()
  })

  // 新增测试：启动流程
  describe('启动流程', () => {
    it('dirty 配置必须保存成功后才能启动', async () => {
      const stateWithDirty = {
        ...defaultState,
        dirtyPaths: new Set(['tank2.height']),
      }
      vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
        if (typeof selector === 'function') {
          return selector(stateWithDirty)
        }
        return stateWithDirty
      })

      const { container } = render(<RuntimeToolbar />)
      const startButton = container.querySelector('[data-testid="start-button"]')
      fireEvent.click(startButton!)

      await waitFor(() => expect(mockSave).toHaveBeenCalled())
      await waitFor(() => expect(systemApi.start).toHaveBeenCalled())
    })

    it('保存失败不调用 Start', async () => {
      const stateWithDirty = {
        ...defaultState,
        dirtyPaths: new Set(['tank2.height']),
      }
      vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
        if (typeof selector === 'function') {
          return selector(stateWithDirty)
        }
        return stateWithDirty
      })
      mockSave.mockRejectedValue(new Error('保存失败'))

      const { container } = render(<RuntimeToolbar />)
      const startButton = container.querySelector('[data-testid="start-button"]')
      fireEvent.click(startButton!)

      await waitFor(() => expect(mockSave).toHaveBeenCalled())
      expect(systemApi.start).not.toHaveBeenCalled()
    })

    it('取消内置模板另存为不调用 Start', async () => {
      const stateWithDirty = {
        ...defaultState,
        dirtyPaths: new Set(['tank2.height']),
      }
      vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
        if (typeof selector === 'function') {
          return selector(stateWithDirty)
        }
        return stateWithDirty
      })
      vi.mocked(templateApi.isBuiltin).mockResolvedValue(true)
      vi.mocked(systemApi.saveYAMLFile).mockResolvedValue('') // 用户取消

      const { container } = render(<RuntimeToolbar />)
      const startButton = container.querySelector('[data-testid="start-button"]')
      fireEvent.click(startButton!)

      await waitFor(() => expect(systemApi.saveYAMLFile).toHaveBeenCalled())
      expect(systemApi.start).not.toHaveBeenCalled()
    })

    it('Start 成功后才进入 SIMULATION_RUNNING', async () => {
      const { container } = render(<RuntimeToolbar />)
      const startButton = container.querySelector('[data-testid="start-button"]')
      fireEvent.click(startButton!)

      await waitFor(() => {
        expect(mockSetRuntimeState).toHaveBeenCalledWith('STARTING')
      })
      await waitFor(() => {
        expect(systemApi.start).toHaveBeenCalled()
      })
      await waitFor(() => {
        expect(mockSetRuntimeState).toHaveBeenCalledWith('SIMULATION_RUNNING')
      })
    })

    it('使用规范 runtimeName second_order_tank', async () => {
      const { container } = render(<RuntimeToolbar />)
      const startButton = container.querySelector('[data-testid="start-button"]')
      fireEvent.click(startButton!)

      await waitFor(() => {
        expect(systemApi.start).toHaveBeenCalledWith(
          expect.objectContaining({
            runtimeName: 'second_order_tank',
          })
        )
      })
    })

    it('使用配置中的 cycleTime', async () => {
      const stateWithCycleTime = {
        ...defaultState,
        draft: { cycleTime: 1.0 },
      }
      vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
        if (typeof selector === 'function') {
          return selector(stateWithCycleTime)
        }
        return stateWithCycleTime
      })
      vi.mocked(useTemplateStore).getState = vi.fn().mockReturnValue(stateWithCycleTime)

      const { container } = render(<RuntimeToolbar />)
      const startButton = container.querySelector('[data-testid="start-button"]')
      fireEvent.click(startButton!)

      await waitFor(() => {
        expect(systemApi.start).toHaveBeenCalledWith(
          expect.objectContaining({
            cycleTime: 1.0,
          })
        )
      })
    })

    it('Start 失败进入 ERROR 并显示错误', async () => {
      vi.mocked(systemApi.start).mockRejectedValue(new Error('进程提前退出'))

      const { container } = render(<RuntimeToolbar />)
      const startButton = container.querySelector('[data-testid="start-button"]')
      fireEvent.click(startButton!)

      await waitFor(() => {
        expect(mockSetRuntimeState).toHaveBeenCalledWith('ERROR')
      })
      await waitFor(() => {
        expect(mockSetRunningIdentity).toHaveBeenCalledWith(null)
      })
      await waitFor(() => {
        expect(container.querySelector('[data-testid="start-error"]')).toBeTruthy()
      })
    })

    it('STARTING 返回时先 Stop 再离开', async () => {
      const stateStarting = {
        ...defaultState,
        runtimeState: 'STARTING' as const,
      }
      vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
        if (typeof selector === 'function') {
          return selector(stateStarting)
        }
        return stateStarting
      })

      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

      const { container } = render(<RuntimeToolbar />)
      const backButton = container.querySelector('[data-testid="back-button"]')
      fireEvent.click(backButton!)

      await waitFor(() => expect(systemApi.stop).toHaveBeenCalled())
      confirmSpy.mockRestore()
    })

    it('RUNNING 返回时先 Stop 再离开', async () => {
      const stateRunning = {
        ...defaultState,
        runtimeState: 'SIMULATION_RUNNING' as const,
      }
      vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
        if (typeof selector === 'function') {
          return selector(stateRunning)
        }
        return stateRunning
      })

      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

      const { container } = render(<RuntimeToolbar />)
      const backButton = container.querySelector('[data-testid="back-button"]')
      fireEvent.click(backButton!)

      await waitFor(() => expect(systemApi.stop).toHaveBeenCalled())
      confirmSpy.mockRestore()
    })

    it('STOPPING 时停止按钮应显示停止中', () => {
      const stateStopping = {
        ...defaultState,
        runtimeState: 'STOPPING' as const,
      }
      vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
        if (typeof selector === 'function') {
          return selector(stateStopping)
        }
        return stateStopping
      })

      const { container } = render(<RuntimeToolbar />)
      expect(container.textContent).toContain('停止中...')
    })

    it('STOPPING 时启动按钮不可见', () => {
      const stateStopping = {
        ...defaultState,
        runtimeState: 'STOPPING' as const,
      }
      vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
        if (typeof selector === 'function') {
          return selector(stateStopping)
        }
        return stateStopping
      })

      const { container } = render(<RuntimeToolbar />)
      expect(container.querySelector('[data-testid="start-button"]')).toBeNull()
    })

    it('Stop 失败不 reset、不离开', async () => {
      const stateRunning = {
        ...defaultState,
        runtimeState: 'SIMULATION_RUNNING' as const,
      }
      vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
        if (typeof selector === 'function') {
          return selector(stateRunning)
        }
        return stateRunning
      })
      vi.mocked(systemApi.stop).mockRejectedValue(new Error('停止失败'))

      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

      const { container } = render(<RuntimeToolbar />)
      const backButton = container.querySelector('[data-testid="back-button"]')
      fireEvent.click(backButton!)

      await waitFor(() => expect(systemApi.stop).toHaveBeenCalled())
      // Stop 失败后不应 reset
      expect(mockReset).not.toHaveBeenCalled()
      // 不应离开页面
      expect(mockSetView).not.toHaveBeenCalled()
      // 应显示错误
      await waitFor(() => {
        expect(container.querySelector('[data-testid="start-error"]')).toBeTruthy()
      })
      confirmSpy.mockRestore()
    })

    it('另存成功后使用新路径、新 hash', async () => {
      const stateWithDirty = {
        ...defaultState,
        dirtyPaths: new Set(['tank2.height']),
      }
      // 模拟另存为后 store 状态更新
      const newStateAfterSave = {
        ...stateWithDirty,
        sourcePath: 'G:/repo/config/new-scheme.yaml',
        savedContentHash: 'newhash123',
        dirtyPaths: new Set(),
      }

      vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
        const state = newStateAfterSave
        if (typeof selector === 'function') {
          return selector(state)
        }
        return state
      })
      vi.mocked(useTemplateStore).getState = vi.fn().mockReturnValue(newStateAfterSave)

      vi.mocked(templateApi.isBuiltin).mockResolvedValue(true)
      vi.mocked(systemApi.start).mockResolvedValue(undefined)
      vi.mocked(systemApi.status).mockResolvedValue({
        running: true,
        apiReady: true,
        configPath: 'G:/repo/config/new-scheme.yaml',
        configHash: 'newhash123',
        startedAt: '2026-07-20T00:00:00Z',
      })

      const { container } = render(<RuntimeToolbar />)
      const startButton = container.querySelector('[data-testid="start-button"]')
      fireEvent.click(startButton!)

      // 应该使用新路径启动
      await waitFor(() => {
        expect(systemApi.start).toHaveBeenCalledWith(
          expect.objectContaining({
            configPath: 'G:/repo/config/new-scheme.yaml',
          })
        )
      })
    })

    it('running identity 完全来自后端 status', async () => {
      vi.mocked(systemApi.start).mockResolvedValue(undefined)
      vi.mocked(systemApi.status).mockResolvedValue({
        running: true,
        apiReady: true,
        configPath: 'G:/repo/config/from-backend.yaml',
        configHash: 'backendhash456',
        startedAt: '2026-07-20T12:00:00Z',
      })

      const { container } = render(<RuntimeToolbar />)
      const startButton = container.querySelector('[data-testid="start-button"]')
      fireEvent.click(startButton!)

      await waitFor(() => {
        expect(mockSetRunningIdentity).toHaveBeenCalledWith({
          path: 'G:/repo/config/from-backend.yaml',
          contentHash: 'backendhash456',
          startedAt: '2026-07-20T12:00:00Z',
        })
      })
    })

    it('传递完整端口/API 参数', async () => {
      vi.mocked(systemApi.start).mockResolvedValue(undefined)

      const { container } = render(<RuntimeToolbar />)
      const startButton = container.querySelector('[data-testid="start-button"]')
      fireEvent.click(startButton!)

      await waitFor(() => {
        expect(systemApi.start).toHaveBeenCalledWith(
          expect.objectContaining({
            port: 18951,
            apiHost: '127.0.0.1',
            apiPort: 8000,
            enableOpcUa: true,
          })
        )
      })
    })

    it('Stop 成功后才 reset 和离开', async () => {
      const stateRunning = {
        ...defaultState,
        runtimeState: 'SIMULATION_RUNNING' as const,
      }
      vi.mocked(useTemplateStore).mockImplementation((selector: any) => {
        if (typeof selector === 'function') {
          return selector(stateRunning)
        }
        return stateRunning
      })
      vi.mocked(systemApi.stop).mockResolvedValue(undefined)

      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

      const { container } = render(<RuntimeToolbar />)
      const backButton = container.querySelector('[data-testid="back-button"]')
      fireEvent.click(backButton!)

      await waitFor(() => expect(systemApi.stop).toHaveBeenCalled())
      // Stop 成功后应 reset
      await waitFor(() => expect(mockReset).toHaveBeenCalled())
      // 应离开页面
      await waitFor(() => expect(mockSetView).toHaveBeenCalledWith('system'))
      confirmSpy.mockRestore()
    })

    it('STARTING 中 Stop 后旧 Start promise 不得恢复运行态', async () => {
      let currentState: any = { ...defaultState }
      vi.mocked(useTemplateStore).mockImplementation((selector: any) => selector(currentState))
      vi.mocked(useTemplateStore).getState = vi.fn().mockImplementation(() => currentState)

      let resolveStart!: () => void
      const startPromise = new Promise<void>((resolve) => { resolveStart = resolve })
      vi.mocked(systemApi.start).mockReturnValue(startPromise)

      const { container, rerender } = render(<RuntimeToolbar />)
      fireEvent.click(container.querySelector('[data-testid="start-button"]')!)
      await waitFor(() => expect(systemApi.start).toHaveBeenCalled())

      currentState = { ...currentState, runtimeState: 'STARTING' as const }
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
  })
})
