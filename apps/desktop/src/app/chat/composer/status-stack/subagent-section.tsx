import { useState } from 'react'

import { SubagentRow } from '@/app/agents'
import { ActivityTimerText } from '@/components/chat/activity-timer-text'
import { StatusRow } from '@/components/chat/status-row'
import { StatusSection } from '@/components/chat/status-section'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { GlyphSpinner } from '@/components/ui/glyph-spinner'
import { useViewedInterval } from '@/hooks/use-viewed-interval'
import { useI18n } from '@/i18n'
import { useSessionSlice } from '@/lib/use-session-slice'
import { requestForOwnedSession } from '@/store/session-states'
import { $subagentsBySession, type SubagentProgress } from '@/store/subagents'

import { SubagentControls } from './subagent-controls'
import { SubagentTranscript } from './subagent-transcript'

interface SubagentSectionProps {
  sessionId: string
}

/** A composer-local roster: never borrow the global Agents panel's scope. */
export function SubagentSection({ sessionId }: SubagentSectionProps) {
  const { t } = useI18n()
  const items = useSessionSlice($subagentsBySession, sessionId)
  const live = items.filter(item => item.status === 'running' || item.status === 'queued')
  const [nowMs, setNowMs] = useState(Date.now)
  const [selected, setSelected] = useState<string | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [stoppingAll, setStoppingAll] = useState(false)
  const [stopFeedback, setStopFeedback] = useState('')
  const hasLive = live.length > 0
  const priced = items.filter(item => typeof item.costUsd === 'number' && Number.isFinite(item.costUsd))
  const reportedCost = priced.reduce((total, item) => total + (item.costUsd ?? 0), 0)

  useViewedInterval(() => setNowMs(Date.now()), 1000, hasLive)

  if (!hasLive) {
    return null
  }

  const stopAll = async () => {
    if (stoppingAll || !live.length) return
    setStoppingAll(true)
    setStopFeedback('')
    // Every interrupt is scoped to the session's own gateway; never route
    // child control to another active gateway during window switches.
    const results = await Promise.allSettled(
      live.map(item =>
        requestForOwnedSession<{ found?: boolean }>(
          sessionId,
          async () => { throw new Error(t.agents.requestRejected) },
          'subagent.interrupt',
          { session_id: sessionId, subagent_id: item.id }
        )
      )
    )
    const accepted = results.filter(result => result.status === 'fulfilled' && result.value.found).length
    setStopFeedback(`${accepted}/${results.length} stop requests accepted`)
    setStoppingAll(false)
  }

  const row = (item: SubagentProgress) => (
    <StatusRow
      expanded={selected === item.id}
      key={item.id}
      leading={
        <GlyphSpinner
          ariaLabel={item.status === 'queued' ? t.agents.queued : t.agents.running}
          className="text-(--ui-purple)"
          spinner="braille"
        />
      }
      onActivate={() => setSelected(selected === item.id ? null : item.id)}
      trailing={
        <ActivityTimerText
          className="shrink-0 text-[0.65rem]"
          seconds={Math.max(0, Math.floor((nowMs - item.startedAt) / 1000))}
        />
      }
      trailingVisible
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs text-(--ui-text-primary)">{item.goal}</span>
        <span className="block truncate text-[0.68rem] text-(--ui-text-tertiary)">
          {item.stream.at(-1)?.text || (item.status === 'queued' ? t.agents.queued : t.agents.waitingActivity)}
        </span>
      </span>
    </StatusRow>
  )

  const detail = live.find(item => item.id === selected)

  return (
    <div className="composer-no-drag min-w-0" data-slot="composer-subagents">
      <StatusSection
        collapsedIndicator={
          <GlyphSpinner
            ariaLabel={live.some(item => item.status === 'running') ? t.agents.running : t.agents.queued}
            className="text-(--ui-purple)"
            spinner="braille"
          />
        }
        icon={<Codicon className="text-(--ui-purple)" name="agent" size="0.8rem" />}
        label={t.statusStack.subagents(live.length)}
      >
        <div className="px-3 py-1 text-[0.68rem] text-(--ui-text-tertiary)" data-slot="meu-worker-budget">
          Meu · max 2 concurrent child runs · {live.length} pending/running
          {priced.length > 0 && ` · reported cost ${reportedCost.toFixed(4)} (${priced.length}/${items.length} with data)`}
        </div>
        <div className="flex items-center justify-between gap-2 px-3 pb-1">
          <span className="text-[0.68rem] text-(--ui-text-tertiary)" role="status">{stopFeedback}</span>
          <Button disabled={stoppingAll} onClick={() => void stopAll()} size="xs" type="button" variant="secondary">
            {stoppingAll ? t.agents.stopRequested : `Meu · ${t.statusStack.stop} all`}
          </Button>
        </div>
        <div className="max-h-[25vh] overflow-y-auto overscroll-y-auto">{live.map(row)}</div>
        {detail && (
          <div
            className="status-subagent-detail max-h-[25vh] overflow-y-auto overscroll-y-auto pr-3 py-2"
            data-slot="composer-subagent-detail"
          >
            <SubagentControls
              key={`${sessionId}:${detail.id}`}
              sessionId={sessionId}
              setText={text => setDrafts(previous => ({ ...previous, [detail.id]: text }))}
              subagentId={detail.id}
              text={drafts[detail.id] ?? ''}
            />
            <SubagentRow node={{ ...detail, children: [] }} nowMs={nowMs} />
            <SubagentTranscript key={`tail:${sessionId}:${detail.id}`} sessionId={sessionId} subagentId={detail.id} />
          </div>
        )}
      </StatusSection>
    </div>
  )
}
