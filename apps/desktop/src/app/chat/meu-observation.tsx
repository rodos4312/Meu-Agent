import { useEffect, useState } from 'react'

import { type MeuObservation, readMeuObservation } from '@/api/meu-observation'
import { usePaneVisible } from '@/components/pane-shell/pane-visibility'

interface Props {
  sessionId: string
  connectionId?: string
  profile?: string
  enabled: boolean
}

/** A viewer of the paired device, never a ThreadMessage or an execution input. */
export function MeuObservationView({ sessionId, connectionId, profile, enabled }: Props) {
  const visible = usePaneVisible()
  const [view, setView] = useState<MeuObservation | null>(null)
  const [stale, setStale] = useState(false)

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined

    async function refresh() {
      try {
        const next = await readMeuObservation(sessionId, connectionId, profile)

        if (cancelled) {
          return
        }

        setView(next)
        setStale(false)
      } catch {
        if (!cancelled) {
          setStale(true)
        }
      }

      if (!cancelled) {
        timer = setTimeout(() => void refresh(), 3000)
      }
    }

    if (enabled && visible) {
      void refresh()
    }

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [connectionId, enabled, profile, sessionId, visible])

  if (!enabled || !visible || !view || view.id !== sessionId) {
    return null
  }

  return (
    <section aria-label="Paired device progress" className="max-h-64 space-y-3 overflow-y-auto py-4 text-sm" data-meu-observation="">
      <p className="text-xs text-muted-foreground">{stale ? 'Paired device · Waiting for connection' : 'Live · Paired device'}</p>
      {view.messages.map(message => (
        <p className="whitespace-pre-wrap break-words" key={message.message_uid}>
          <strong>{message.role === 'user' ? 'You' : 'Meu'}: </strong>{message.content}
        </p>
      ))}
      <p className="whitespace-pre-wrap break-words">{view.draft || (view.busy ? 'The agent is working…' : '')}</p>
    </section>
  )
}
