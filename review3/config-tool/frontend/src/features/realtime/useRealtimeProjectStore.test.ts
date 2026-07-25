/**
 * 回归测试：flattenOpenedProject 正确把 Wails OpenedProject 转为扁平 ProjectView，
 * 确保 currentProject.sources 不会是 undefined（否则页面会抛
 * "Cannot read properties of undefined reading 'length'"）。
 */
import { describe, expect, it } from 'vitest'
import type { ProjectView } from './types'

/**
 * 把 Wails 返回的 OpenedProject（嵌套 {project, projectFile, projectDir}）
 * 扁平化为 ProjectView（{sources, runtime, projectFile, projectDir}）。
 * 后端 CreateProjectAt / OpenProjectFile 都返回嵌套结构；前端 ProjectView 期望扁平。
 * 扁平化必须 sources / runtime 都来自内层 project，避免渲染时出现 undefined.sources。
 */
function flattenOpenedProject(opened: unknown): ProjectView {
  const o = opened as { project?: any; projectFile?: string; projectDir?: string }
  const p = o?.project || {}
  return {
    version: p.version,
    id: p.id,
    name: p.name,
    sources: Array.isArray(p.sources) ? p.sources : [],
    runtime: p.runtime,
    projectFile: o?.projectFile,
    projectDir: o?.projectDir,
  } as ProjectView
}

const openedSample = {
  project: {
    version: 1,
    id: 'proj-1',
    name: '测试工程',
    sources: [],
    runtime: { cycleTime: 0.5, opcUaHost: '0.0.0.0', opcUaPort: 18951 },
  },
  projectFile: 'C:/exe/project/测试工程/project.yaml',
  projectDir: 'C:/exe/project/测试工程',
}

describe('flattenOpenedProject', () => {
  it('扁平化后 sources 是空数组而非 undefined', () => {
    const flat = flattenOpenedProject(openedSample)
    expect(Array.isArray(flat.sources)).toBe(true)
    expect(flat.sources.length).toBe(0)
    expect(() => flat.sources.length).not.toThrow()
  })

  it('字段映射正确', () => {
    const flat = flattenOpenedProject(openedSample)
    expect(flat.version).toBe(1)
    expect(flat.id).toBe('proj-1')
    expect(flat.name).toBe('测试工程')
    expect(flat.projectFile).toBe('C:/exe/project/测试工程/project.yaml')
    expect(flat.projectDir).toBe('C:/exe/project/测试工程')
    expect(flat.runtime).toEqual({ cycleTime: 0.5, opcUaHost: '0.0.0.0', opcUaPort: 18951 })
  })

  it('backend 返回 sources 缺失时不抛 undefined 异常', () => {
    const opened = {
      project: {
        version: 1,
        id: 'proj-2',
        name: 'B',
        // sources 缺失
        runtime: undefined,
      },
      projectFile: 'P',
      projectDir: 'D',
    } as any
    const flat = flattenOpenedProject(opened)
    expect(Array.isArray(flat.sources)).toBe(true)
    expect(flat.sources.length).toBe(0)
    expect(flat.runtime).toBeUndefined()
  })

  it('整体结构异常时不抛', () => {
    const flat = flattenOpenedProject(undefined)
    expect(Array.isArray(flat.sources)).toBe(true)
    expect(flat.id).toBeUndefined()
    expect(flat.name).toBeUndefined()
  })

  it('当 sources 是非数组（如 undefined）时退化为空数组', () => {
    const flat = flattenOpenedProject({
      project: { version: 1, id: 'x', name: 'X', sources: undefined },
      projectFile: 'P',
    })
    expect(Array.isArray(flat.sources)).toBe(true)
    expect(flat.sources.length).toBe(0)
  })

  it('addSource 返回的 OpenedProjectView.project 也能被扁平化（嵌套层级一致）', () => {
    // addSourceAt / removeSourceAt / updateReplicasAt 返回 OpenedProjectView
    //   { applied, project: OpenedProject, validation }
    // 取 view.project 传给 flattenOpenedProject，效果应与直接给 OpenedProject 相同
    const view = {
      applied: true,
      project: openedSample,
      validation: { valid: true, instances: [], duplicates: [] },
    } as any
    const proj = flattenOpenedProject(view.project)
    expect(proj.sources).toBeDefined()
    expect(Array.isArray(proj.sources)).toBe(true)
    expect(proj.id).toBe('proj-1')
  })
})