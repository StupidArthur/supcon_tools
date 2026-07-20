/**
 * Prospective acceptance helper: load a source module only if it exists on disk.
 * Uses @vite-ignore so missing modules do not crash Vitest collection.
 */
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { expect } from 'vitest'

const acceptanceRoot = path.dirname(fileURLToPath(import.meta.url))

export async function importContractModule(
  absoluteCandidates: string[],
  contractId: string,
  hint: string,
): Promise<Record<string, unknown>> {
  const existing = absoluteCandidates.find((candidate) => existsSync(candidate))
  if (!existing) {
    expect.fail(
      `${contractId}: module missing. ${hint} Candidates: ${absoluteCandidates.join(' | ')}`,
    )
  }
  const href = pathToFileURL(existing).href
  try {
    return (await import(/* @vite-ignore */ href)) as Record<string, unknown>
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    expect.fail(`${contractId}: failed to import ${existing} (${message}). ${hint}`)
  }
}

export function frontendSrc(...parts: string[]): string {
  return path.resolve(acceptanceRoot, '..', 'src', ...parts)
}

export function candidatesFor(baseWithoutExt: string): string[] {
  return [`${baseWithoutExt}.ts`, `${baseWithoutExt}.tsx`, `${baseWithoutExt}.js`]
}
