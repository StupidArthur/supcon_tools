/**
 * Unicode Save As adapter (stage 8).
 * No relative imports — prospective acceptance loads via file://.
 */

type SaveAsImpl = (path: string) => Promise<unknown>

let saveAsImpl: SaveAsImpl | null = null

/** Wire real template store save from the page. */
export function bindSaveAs(impl: SaveAsImpl): void {
  saveAsImpl = impl
}

/**
 * Save draft to an explicit path (Unicode supported by Go SaveTemplate).
 */
export async function saveAs(path: string): Promise<unknown> {
  if (!path) {
    throw new Error('saveAs path is required')
  }
  if (!saveAsImpl) {
    throw new Error('saveAs not bound to template store')
  }
  return saveAsImpl(path)
}
