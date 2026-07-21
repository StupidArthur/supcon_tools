/**
 * Dialog option descriptors for batch CSV vs YAML (stage 7).
 * No relative imports — prospective acceptance loads via file://.
 */

export function batchExportDialogOptions(): {
  Title: string
  DefaultFilename: string
  filters: Array<{ DisplayName: string; Pattern: string }>
} {
  return {
    Title: '导出批量仿真 CSV',
    DefaultFilename: 'batch_result.csv',
    filters: [{ DisplayName: 'CSV 文件', Pattern: '*.csv' }],
  }
}

export function yamlDialogOptions(): {
  Title: string
  DefaultFilename: string
  filters: Array<{ DisplayName: string; Pattern: string }>
} {
  return {
    Title: '保存 YAML 配置文件',
    DefaultFilename: 'config.yaml',
    filters: [{ DisplayName: 'YAML 文件', Pattern: '*.yaml;*.yml' }],
  }
}
