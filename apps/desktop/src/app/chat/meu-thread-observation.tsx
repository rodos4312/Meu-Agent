import { useStore } from '@nanostores/react'

import { useTranscriptWindow } from '@/components/assistant-ui/thread/transcript-window'

import { useComposerScope } from './composer/scope'
import { MeuObservationView } from './meu-observation'
import { useSessionView } from './session-view'

/** Bind a read-only projection to this pane's durable session and owner. */
export function MeuThreadObservation({ profile }: { profile?: string }) {
  const session = useSessionView()
  const id = useStore(session.$storedId)
  const busy = useStore(session.$busy)
  const scope = useComposerScope()
  const { isHistorical } = useTranscriptWindow()
  const ownerProfile = scope.profile || profile

  return id ? (
    <MeuObservationView
      connectionId={scope.connectionId || undefined}
      enabled={!busy && !isHistorical}
      key={JSON.stringify([id, scope.connectionId, ownerProfile])}
      profile={ownerProfile}
      sessionId={id}
    />
  ) : null
}
