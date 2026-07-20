/**
 * Stage 0 reviewer acceptance: legacy entries remain reachable from Toolbar/App.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../../src/lib/api', () => ({
  configApi: {
    exportYAML: vi.fn(),
    importYAML: vi.fn(),
    validate: vi.fn(),
  },
  systemApi: {
    openYAMLFile: vi.fn(),
    saveYAMLFile: vi.fn(),
  },
}))

vi.mock('../../wailsjs/runtime/runtime', () => ({
  EventsOn: vi.fn(),
}))

import { Toolbar } from '../../src/components/Toolbar'
import { useCanvasStore } from '../../src/store/useCanvasStore'

describe('stage 0 legacy views acceptance', () => {
  afterEach(() => {
    cleanup()
  })

  it('Toolbar still exposes template, system, simulation, and advanced DSL entries', () => {
    useCanvasStore.setState({ view: 'template' })
    render(<Toolbar />)
    expect(screen.getByText('二阶水箱模板')).toBeTruthy()
    expect(screen.getByText('系统管理')).toBeTruthy()
    expect(screen.getByText('仿真运行')).toBeTruthy()
    expect(screen.getByText('高级组态')).toBeTruthy()
  })

  it('Toolbar can switch among legacy views without deleting entries', async () => {
    const user = userEvent.setup()
    useCanvasStore.setState({ view: 'template' })
    const { getByText } = render(<Toolbar />)
    await user.click(getByText('系统管理'))
    expect(useCanvasStore.getState().view).toBe('system')
    await user.click(getByText('仿真运行'))
    expect(useCanvasStore.getState().view).toBe('simulation')
    await user.click(getByText('高级组态'))
    expect(useCanvasStore.getState().view).toBe('config')
    await user.click(getByText('二阶水箱模板'))
    expect(useCanvasStore.getState().view).toBe('template')
  })
})
