import { SecondOrderTankPage } from './secondOrderTank/SecondOrderTankPage'

// 阶段 1 唯一支持的固定模板入口。
// 后续阶段会在这里做模板列表、切换与共享 toolbar。
export function TemplateWorkspace() {
  return <SecondOrderTankPage />
}