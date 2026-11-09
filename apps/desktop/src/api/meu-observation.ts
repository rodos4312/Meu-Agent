import { capabilityScoped, hermesApi, sessionReadOwnerPin } from './client'

export interface MeuObservation {
  id: string
  busy: boolean
  draft: string
  messages: { role: 'user' | 'assistant'; content: string; message_uid: string }[]
}

export function decodeMeuObservation(value: unknown, id: string): MeuObservation | null {
  if (value === null) {
    return null
  }

  const view = value as Partial<MeuObservation> | undefined

  if (!view || view.id !== id || typeof view.busy !== 'boolean' || typeof view.draft !== 'string' ||
      view.draft.length > 256 * 1024 || !Array.isArray(view.messages) || view.messages.length > 1000) {
    throw new Error('Invalid paired observation')
  }

  const seen = new Set<string>()
  let size = 0

  for (const row of view.messages) {
    if (!row || !['user', 'assistant'].includes(row.role) || typeof row.content !== 'string' ||
        typeof row.message_uid !== 'string' || !/^[0-9a-f]{32}$/.test(row.message_uid) || seen.has(row.message_uid)) {
      throw new Error('Invalid paired observation text')
    }

    seen.add(row.message_uid)
    size += row.content.length
  }

  if (size > 256 * 1024) {
    throw new Error('Paired observation is too large')
  }

  return view as MeuObservation
}

export async function readMeuObservation(id: string, connectionId?: string, profile?: string): Promise<MeuObservation | null> {
  const scope = { connectionId, profile }
  const route = { ...capabilityScoped(scope), ...sessionReadOwnerPin(id, scope) }
  const query = route.profile ? `?profile=${encodeURIComponent(route.profile)}` : ''

  const result = await hermesApi<{ observation: MeuObservation | null }>({
    ...route,
    path: `/api/sessions/${encodeURIComponent(id)}/meu-observation${query}`,
    passive: true
  })

  return decodeMeuObservation(result.observation, id)
}
