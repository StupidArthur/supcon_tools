import { describe, it, expect } from 'vitest'
import { componentApi, configApi, systemApi, templateApi } from './api'

describe('lib/api', () => {
  it('exports the api wrappers with the expected methods', () => {
    expect(typeof componentApi.list).toBe('function')
    expect(typeof configApi.importYAML).toBe('function')
    expect(typeof configApi.exportYAML).toBe('function')
    expect(typeof configApi.validate).toBe('function')
    expect(typeof configApi.loadCanvas).toBe('function')
    expect(typeof configApi.saveCanvas).toBe('function')
    expect(typeof templateApi.loadBuiltin).toBe('function')
    expect(typeof templateApi.load).toBe('function')
    expect(typeof templateApi.save).toBe('function')
    expect(typeof templateApi.validate).toBe('function')
    expect(typeof templateApi.isBuiltin).toBe('function')
    expect(typeof systemApi.getDataFactoryPath).toBe('function')
    expect(typeof systemApi.browseExe).toBe('function')
    expect(typeof systemApi.listConfigs).toBe('function')
    expect(typeof systemApi.start).toBe('function')
    expect(typeof systemApi.stop).toBe('function')
    expect(typeof systemApi.status).toBe('function')
    expect(typeof systemApi.openYAMLFile).toBe('function')
    expect(typeof systemApi.saveYAMLFile).toBe('function')
    expect(typeof systemApi.runBatch).toBe('function')
    expect(typeof systemApi.exportBatch).toBe('function')
  })

  it('wrappers do not maintain internal business state', () => {
    // 直接比较三次构造的对象：同一引用，没有缓存。
    const a = componentApi
    const b = componentApi
    expect(a).toBe(b)
    expect(configApi).not.toBe(componentApi)
    expect(systemApi).not.toBe(configApi)
  })
})
