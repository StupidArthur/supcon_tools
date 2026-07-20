import { useTemplateStore } from './useTemplateStore'
import { SecondOrderTankInspector } from './secondOrderTank/SecondOrderTankInspector'

// ObjectInspector 是模板工作区右侧检查器的统一入口。
// 根据当前选中的模板类型渲染对应的检查器组件。
export function ObjectInspector() {
  const templateId = useTemplateStore((s) => s.templateId)
  const selectedObjectId = useTemplateStore((s) => s.selectedObjectId)
  const draft = useTemplateStore((s) => s.draft)
  const dirtyPaths = useTemplateStore((s) => s.dirtyPaths)
  const validationErrors = useTemplateStore((s) => s.validationErrors)
  const validationWarnings = useTemplateStore((s) => s.validationWarnings)
  const editField = useTemplateStore((s) => s.editField)

  if (!draft) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
        正在加载...
      </div>
    )
  }

  // 阶段 2 只支持 second_order_tank 模板
  if (templateId === 'second_order_tank') {
    return (
      <SecondOrderTankInspector
        selectedObjectId={selectedObjectId}
        draft={draft}
        dirtyPaths={dirtyPaths}
        validationErrors={validationErrors}
        validationWarnings={validationWarnings}
        onEditField={editField}
      />
    )
  }

  // 未知模板类型
  return (
    <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
      不支持的模板类型
    </div>
  )
}
