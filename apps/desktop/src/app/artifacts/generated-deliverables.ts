import { artifactContentHash, artifactDownloadName, detectArtifact } from '@/lib/artifact-detect'

import type { ArtifactRecord } from './artifact-utils'

export const MAX_INLINE_DELIVERABLE_CHARS = 512_000
export const MAX_INDEX_INLINE_CHARS = 2_000_000

/** Completed assistant fences only; reuse the chat's document/snippet policy. */
export function generatedDeliverables(text: string): NonNullable<ArtifactRecord['inline']>[] {
  const found = [] as NonNullable<ArtifactRecord['inline']>[]
  let opening: { marker: string; length: number; language: string; lines: string[] } | null = null

  for (const line of text.split('\n')) {
    if (!opening) {
      const fence = /^ {0,3}(`{3,}|~{3,})([^\r]*)\r?$/.exec(line)

      if (fence) {
        opening = { marker: fence[1][0], length: fence[1].length, language: fence[2].trim().split(/\s+/)[0], lines: [] }
      }

      continue
    }

    const close = /^ {0,3}(`{3,}|~{3,})\s*$/.exec(line)

    if (!close || close[1][0] !== opening.marker || close[1].length < opening.length) {
      opening.lines.push(line)

      continue
    }

    const content = opening.lines.join('\n').trim()
    const detection = detectArtifact(opening.language, content)

    if (detection) {
      found.push({
        ...detection,
        hash: artifactContentHash(content),
        name: artifactDownloadName(detection.kind, detection.language, detection.title),
        content: content.length <= MAX_INLINE_DELIVERABLE_CHARS ? content : undefined
      })
    }

    opening = null

    if (found.length === 24) {
      break
    }
  }

  return found
}
