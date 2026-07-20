import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SecondOrderTankInspector } from './SecondOrderTankInspector'
import type { DraftConfig, SelectedObjectId, ValidationIssue } from '../types'

// 测试用默认 draft 配置
const defaultDraft: DraftConfig = {
  cycleTime: 0.5,
  clockMode: 'REALTIME',
  sourceFlow: 0.0012, // 72 L/min
  valve: {
    fullTravelTime: 12,
    initialOpening: 50,
    flowCoefficient: 1,
    minOpening: 0,
    maxOpening: 100,
  },
  tank1: {
    height: 1.2,
    radius: 0.15,
    outletArea: 0.00025,
    initialLevel: 0.15,
  },
  tank2: {
    height: 1.2,
    radius: 0.15,
    outletArea: 0.00020,
    initialLevel: 0.10,
  },
  pid: {
    PB: 30,
    TI: 90,
    TD: 20,
    KD: 10,
    SV: 0.8,
    MV: 0,
    MODE: 5,
    SWPN: 1,
    SVSCL: 0,
    SVSCH: 1.2,
    SVL: 0,
    SVH: 1.2,
    MVSCL: 0,
    MVSCH: 100,
    MVL: 0,
    MVH: 100,
  },
}

describe('SecondOrderTankInspector', () => {
  describe('未选中对象', () => {
    it('应显示模板说明', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId={null}
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('单阀门二阶水箱')
      expect(container.textContent).toContain('模板说明')
    })

    it('应显示默认工况（来自 draft）', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId={null}
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('水源流量：72.0 L/min')
      expect(container.textContent).toContain('Tank 1 初始液位：0.150 m')
      expect(container.textContent).toContain('Tank 2 初始液位：0.100 m')
      expect(container.textContent).toContain('PID SV：0.800 m')
    })

    it('应显示校验错误', () => {
      const errors: ValidationIssue[] = [
        { path: 'sourceFlow', level: 'error', message: '水源流量不能为负' },
      ]
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId={null}
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={errors}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('水源流量不能为负')
    })

    it('应显示校验警告', () => {
      const warnings: ValidationIssue[] = [
        { path: 'pid.SV', level: 'warning', message: 'SV 超过 Tank 2 高度' },
      ]
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId={null}
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={warnings}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('SV 超过 Tank 2 高度')
    })
  })

  describe('选中 LT-201', () => {
    it('应显示标题和信号绑定', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="lt_201"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('液位测量')
      expect(container.textContent).toContain('lt_201 · LT')
      expect(container.textContent).toContain('tank_2.level')
      expect(container.textContent).toContain('pid2.PV')
    })

    it('应显示虚拟仪表说明', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="lt_201"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('LT-201 是虚拟仪表，不包含可编辑参数')
    })
  })

  describe('选中水源', () => {
    it('应显示标题', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="source_flow"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('水源')
      expect(container.textContent).toContain('source_flow · Variable')
    })

    it('应显示三个页签', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="source_flow"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('组态')
      expect(container.textContent).toContain('运行')
      expect(container.textContent).toContain('趋势')
    })

    it('应显示水源流量字段（L/min）', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="source_flow"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('水源流量')
      expect(container.textContent).toContain('L/min')
    })

    it('应显示周期字段（appliesTo: all）', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="source_flow"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('控制周期')
    })

    it('应显示 YAML 参数名', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="source_flow"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('program.source_flow.value')
    })

    it('应显示合法范围', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="source_flow"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('范围：')
    })
  })

  describe('选中阀门', () => {
    it('应显示标题', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="valve_1"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('调节阀')
      expect(container.textContent).toContain('valve_1 · VALVE')
    })

    it('应显示基础字段', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="valve_1"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('满行程时间')
      expect(container.textContent).toContain('初始开度')
    })

    it('应折叠高级字段', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="valve_1"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      // 高级字段默认折叠
      expect(container.textContent).not.toContain('流量系数')
      expect(container.textContent).not.toContain('最小开度')

      // 点击展开高级参数
      const toggleButton = container.querySelector('[data-testid="toggle-advanced"]')
      fireEvent.click(toggleButton!)
      expect(container.textContent).toContain('流量系数')
      expect(container.textContent).toContain('最小开度')
    })
  })

  describe('选中 Tank 2', () => {
    it('应显示标题', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="tank_2"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('下游水箱')
      expect(container.textContent).toContain('tank_2 · CYLINDRICAL_TANK')
    })

    it('应显示基础字段', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="tank_2"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('高度')
      expect(container.textContent).toContain('半径')
      expect(container.textContent).toContain('初始液位')
    })

    it('应显示容量（L）', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="tank_2"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('容量')
      expect(container.textContent).toContain('L')
    })

    it('初始液位范围应来自当前水箱高度', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="tank_2"
          draft={{ ...defaultDraft, tank2: { ...defaultDraft.tank2, height: 1.7 } }}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      const field = container.querySelector('[data-testid="field-tank2.initialLevel"]')
      expect(field?.textContent).toContain('范围：[0, 1.7] m')
    })

    it('高级参数应包含出口直径（mm）', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="tank_2"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      // 点击展开高级参数
      const toggleButton = container.querySelector('[data-testid="toggle-advanced"]')
      fireEvent.click(toggleButton!)
      expect(container.textContent).toContain('出口直径')
      expect(container.textContent).toContain('mm')
    })

    it('应显示 dirty 标记', () => {
      const dirtyPaths = new Set(['tank2.height'])
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="tank_2"
          draft={defaultDraft}
          dirtyPaths={dirtyPaths}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      // 应该有 dirty 标记点
      const heightFields = container.querySelectorAll('[data-testid="field-tank2.height"]')
      const heightField = heightFields[heightFields.length - 1]
      expect(heightField.querySelector('[title="已修改"]')).toBeTruthy()
    })

    it('应显示校验错误', () => {
      const errors: ValidationIssue[] = [
        { path: 'tank2.height', level: 'error', message: '高度必须大于 0' },
      ]
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="tank_2"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={errors}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('高度必须大于 0')
    })
  })

  describe('选中 PID', () => {
    it('应显示标题', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="pid2"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('液位控制器')
      expect(container.textContent).toContain('pid2 · PID')
    })

    it('应显示基础字段', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="pid2"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('PB')
      expect(container.textContent).toContain('TI')
      expect(container.textContent).toContain('TD')
      expect(container.textContent).toContain('SV')
    })

    it('应显示 YAML 参数名', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="pid2"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('program.pid2.params.PB')
    })

    it('应折叠高级字段', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="pid2"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      // 高级字段默认折叠
      expect(container.textContent).not.toContain('KD')
      expect(container.textContent).not.toContain('SWPN')

      // 点击展开高级参数
      const toggleButton = container.querySelector('[data-testid="toggle-advanced"]')
      fireEvent.click(toggleButton!)
      expect(container.textContent).toContain('KD')
      expect(container.textContent).toContain('SWPN')
    })
  })

  describe('页签切换', () => {
    it('应切换到运行页签', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="tank_2"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      // 点击最后一个"运行"按钮
      const runtimeButtons = container.querySelectorAll('[data-testid="tab-runtime"]')
      fireEvent.click(runtimeButtons[runtimeButtons.length - 1])
      expect(container.textContent).toContain('未运行')
      expect(container.textContent).toContain('启动仿真后显示实时值')
    })

    it('应切换到趋势页签', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="tank_2"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      // 点击最后一个"趋势"按钮
      const trendButtons = container.querySelectorAll('[data-testid="tab-trend"]')
      fireEvent.click(trendButtons[trendButtons.length - 1])
      expect(container.textContent).toContain('推荐将以下位号添加到趋势图：')
      expect(container.textContent).toContain('tank_2.level')
      expect(container.textContent).toContain('pid2.SV')
    })

    it('趋势页签应显示正确的推荐位号', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="pid2"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      // 点击最后一个"趋势"按钮
      const trendButtons = container.querySelectorAll('[data-testid="tab-trend"]')
      fireEvent.click(trendButtons[trendButtons.length - 1])
      expect(container.textContent).toContain('pid2.PV')
      expect(container.textContent).toContain('pid2.SV')
      expect(container.textContent).toContain('pid2.MV')
      expect(container.textContent).toContain('pid2.MODE')
    })
  })

  describe('字段编辑', () => {
    it('修改字段应触发 onEditField（带单位换算）', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="source_flow"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      // 取水源流量输入框
      const flowInputs = container.querySelectorAll('[data-testid="input-sourceFlow"]')
      const flowInput = flowInputs[flowInputs.length - 1]
      // 输入 80 L/min
      fireEvent.change(flowInput, { target: { value: '80' } })
      fireEvent.blur(flowInput)

      // 应该转换为 m³/s 调用 onEditField
      expect(onEditField).toHaveBeenCalledWith('sourceFlow', 80 / 60_000)
    })

    it('应显示生效方式', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="tank_2"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('重启生效')
    })

    it('应显示帮助文本', () => {
      const onEditField = vi.fn()
      const { container } = render(
        <SecondOrderTankInspector
          selectedObjectId="source_flow"
          draft={defaultDraft}
          dirtyPaths={new Set()}
          validationErrors={[]}
          validationWarnings={[]}
          onEditField={onEditField}
        />
      )

      expect(container.textContent).toContain('恒定水源供给流量')
    })
  })
})
