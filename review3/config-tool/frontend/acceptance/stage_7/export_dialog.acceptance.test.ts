/**
 * Stage 7 prospective: YAML vs CSV dialog separation.
 */
import { describe, expect, it } from 'vitest'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

describe('stage 7 export dialog acceptance', () => {
  it('batch export uses CSV dialog filters, not YAML', async () => {
    const mod = await importContractModule(
      candidatesFor(frontendSrc('features', 'templates', 'batchExport')),
      'STAGE7-CSV-005',
      'Public batchExportDialogOptions must request CSV filters, distinct from YAML open/save.',
    )
    const opts = mod.batchExportDialogOptions as () => { filters: Array<{ Pattern: string }> }
    const yamlOpts = mod.yamlDialogOptions as (() => { filters: Array<{ Pattern: string }> }) | undefined
    const exportFilters = opts().filters.map((f) => f.Pattern).join(';')
    expect(exportFilters.toLowerCase(), 'STAGE7-CSV-005').toMatch(/csv/)
    expect(exportFilters.toLowerCase(), 'STAGE7-CSV-005').not.toMatch(/yaml|\.yml/)
    if (yamlOpts) {
      const y = yamlOpts().filters.map((f) => f.Pattern).join(';')
      expect(y.toLowerCase()).toMatch(/yaml|\.yml/)
    }
  })
})
