/**
 * Stage 0 reviewer acceptance: API wrappers must be pure pass-throughs.
 * Mock Wails bindings; assert argument forwarding, Promise identity, and no swallowed errors.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const ComponentBinding = vi.hoisted(() => ({
  List: vi.fn(),
}))
const ConfigBinding = vi.hoisted(() => ({
  ImportYAML: vi.fn(),
  ExportYAML: vi.fn(),
  Validate: vi.fn(),
  LoadCanvas: vi.fn(),
  SaveCanvas: vi.fn(),
}))
const SystemBinding = vi.hoisted(() => ({
  GetDataFactoryPath: vi.fn(),
  BrowseExe: vi.fn(),
  ListConfigs: vi.fn(),
  Start: vi.fn(),
  Stop: vi.fn(),
  Status: vi.fn(),
  OpenYAMLFile: vi.fn(),
  SaveYAMLFile: vi.fn(),
  RunBatch: vi.fn(),
  ExportBatch: vi.fn(),
}))
const TemplateConfigBinding = vi.hoisted(() => ({
  LoadBuiltinTemplate: vi.fn(),
  LoadTemplate: vi.fn(),
  SaveTemplate: vi.fn(),
  ValidateTemplateConfig: vi.fn(),
  IsBuiltinTemplate: vi.fn(),
}))

// Paths resolve from this file to frontend/wailsjs (same modules api.ts imports).
vi.mock('../../wailsjs/go/bindings/ComponentBinding', () => ComponentBinding)
vi.mock('../../wailsjs/go/bindings/ConfigBinding', () => ConfigBinding)
vi.mock('../../wailsjs/go/bindings/SystemBinding', () => SystemBinding)
vi.mock('../../wailsjs/go/bindings/TemplateConfigBinding', () => TemplateConfigBinding)

import { componentApi, configApi, systemApi } from '../../src/lib/api'

describe('stage 0 api wrapper acceptance', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('forwards componentApi.list without wrapping state', async () => {
    const promise = Promise.resolve([{ name: 'PID' }])
    ComponentBinding.List.mockReturnValue(promise)
    const result = componentApi.list()
    expect(result).toBe(promise)
    await expect(result).resolves.toEqual([{ name: 'PID' }])
    expect(ComponentBinding.List).toHaveBeenCalledOnce()
  })

  it('forwards every configApi method with original arguments', async () => {
    const canvas = { nodes: [], edges: [] }
    const path = 'C:/tmp/a.yaml'
    ConfigBinding.ImportYAML.mockResolvedValue(canvas)
    ConfigBinding.ExportYAML.mockResolvedValue(undefined)
    ConfigBinding.Validate.mockResolvedValue({ valid: true })
    ConfigBinding.LoadCanvas.mockResolvedValue(canvas)
    ConfigBinding.SaveCanvas.mockResolvedValue(undefined)

    await configApi.importYAML(path)
    await configApi.exportYAML(canvas, path)
    await configApi.validate(canvas)
    await configApi.loadCanvas(path)
    await configApi.saveCanvas(canvas, path)

    expect(ConfigBinding.ImportYAML).toHaveBeenCalledWith(path)
    expect(ConfigBinding.ExportYAML).toHaveBeenCalledWith(canvas, path)
    expect(ConfigBinding.Validate).toHaveBeenCalledWith(canvas)
    expect(ConfigBinding.LoadCanvas).toHaveBeenCalledWith(path)
    expect(ConfigBinding.SaveCanvas).toHaveBeenCalledWith(canvas, path)
  })

  it('forwards every systemApi method and does not swallow rejections', async () => {
    const boom = new Error('binding failed')
    SystemBinding.GetDataFactoryPath.mockRejectedValue(boom)
    await expect(systemApi.getDataFactoryPath()).rejects.toBe(boom)

    const startParams = { path: 'x.yaml', mode: 'REALTIME' }
    SystemBinding.BrowseExe.mockResolvedValue('df.exe')
    SystemBinding.ListConfigs.mockResolvedValue(['a.yaml'])
    SystemBinding.Start.mockResolvedValue({ ok: true })
    SystemBinding.Stop.mockResolvedValue(undefined)
    SystemBinding.Status.mockResolvedValue({ running: false })
    SystemBinding.OpenYAMLFile.mockResolvedValue('open.yaml')
    SystemBinding.SaveYAMLFile.mockResolvedValue('save.yaml')
    SystemBinding.RunBatch.mockResolvedValue({ ok: true })
    SystemBinding.ExportBatch.mockResolvedValue({ ok: true })

    await systemApi.browseExe()
    await systemApi.listConfigs()
    await systemApi.start(startParams)
    await systemApi.stop()
    await systemApi.status()
    await systemApi.openYAMLFile()
    await systemApi.saveYAMLFile()
    await systemApi.runBatch('c.yaml', 10)
    await systemApi.exportBatch('c.yaml', 10, 'out.csv')

    expect(SystemBinding.BrowseExe).toHaveBeenCalledOnce()
    expect(SystemBinding.ListConfigs).toHaveBeenCalledOnce()
    expect(SystemBinding.Start).toHaveBeenCalledWith(startParams)
    expect(SystemBinding.Stop).toHaveBeenCalledOnce()
    expect(SystemBinding.Status).toHaveBeenCalledOnce()
    expect(SystemBinding.OpenYAMLFile).toHaveBeenCalledOnce()
    expect(SystemBinding.SaveYAMLFile).toHaveBeenCalledOnce()
    expect(SystemBinding.RunBatch).toHaveBeenCalledWith('c.yaml', 10)
    expect(SystemBinding.ExportBatch).toHaveBeenCalledWith('c.yaml', 10, 'out.csv')
  })

  it('does not cache business results across calls', async () => {
    SystemBinding.Status.mockResolvedValueOnce({ running: false }).mockResolvedValueOnce({
      running: true,
    })
    const first = await systemApi.status()
    const second = await systemApi.status()
    expect(first).toEqual({ running: false })
    expect(second).toEqual({ running: true })
    expect(first).not.toBe(second)
  })
})
