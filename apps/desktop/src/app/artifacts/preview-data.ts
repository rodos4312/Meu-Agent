import { fileUrlToNativePath } from '@hermes/shared'

import { hermesApiAs, type ResolvedOwner } from '@/api/client'
import type { HermesReadFileTextResult } from '@/global'
import { localPreviewTarget } from '@/lib/local-preview'
import { resolveMediaDisplaySrc } from '@/lib/media'

import type { ArtifactRecord } from './artifact-utils'

export interface DeliverablePreviewData extends HermesReadFileTextResult {
  kind: 'html' | 'image' | 'pdf' | 'text'
  dataUrl?: string
}

/** All disk reads go to the captured owner, including native Windows files. */
export async function readDeliverablePreview(
  artifact: ArtifactRecord,
  owner: ResolvedOwner
): Promise<DeliverablePreviewData> {
  if (artifact.inline) {
    if (artifact.inline.content === undefined) {
      throw new Error('inline_preview_limit')
    }

    return {
      path: '',
      kind: artifact.inline.kind === 'html' ? 'html' : artifact.inline.kind === 'svg' ? 'image' : 'text',
      dataUrl:
        artifact.inline.kind === 'svg'
          ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(artifact.inline.content)}`
          : undefined,
      text: artifact.inline.content,
      language: artifact.inline.language,
      byteSize: new TextEncoder().encode(artifact.inline.content).length
    }
  }

  if (artifact.kind === 'image' && /^(?:https?:\/\/|data:image\/)/i.test(artifact.value)) {
    if (artifact.value.length > 24_000_000) {
      throw new Error('invalid_preview_data')
    }

    return {
      path: artifact.value,
      kind: 'image',
      text: '',
      dataUrl: await resolveMediaDisplaySrc(artifact.value, owner)
    }
  }

  const path = artifact.value.startsWith('file:') ? fileUrlToNativePath(artifact.value) : artifact.value

  if (!path) {
    throw new Error('invalid_artifact_path')
  }

  const target = localPreviewTarget(path)
  const query = new URLSearchParams({ path, session_id: artifact.sessionId })
  const kind = target?.previewKind

  if (kind === 'image' || kind === 'pdf') {
    const result = await hermesApiAs<string | { dataUrl: string }>(owner, { path: `/api/fs/read-data-url?${query}` })
    const dataUrl = typeof result === 'string' ? result : result.dataUrl

    if (!/^data:(?:image\/[^;,]+|application\/pdf);base64,/i.test(dataUrl) || dataUrl.length > 24_000_000) {
      throw new Error('invalid_preview_data')
    }

    return { path, kind, text: '', dataUrl }
  }

  const result = await hermesApiAs<HermesReadFileTextResult>(owner, { path: `/api/fs/read-text?${query}` })

  return { ...result, kind: kind === 'html' ? 'html' : 'text' }
}
