/**
 * Optional details of a coding task: "Why these files?" (every score component of the ranking),
 * the project memory that was used or ignored as stale, memory notes the finished task proposes
 * (saved only on an explicit Accept), and the intelligence/route metrics. Collapsed by default.
 */

import { Button, useQuery, useQueryClient } from '@hermes/plugin-sdk'
import { useState } from 'react'

import { codingApi } from './api'
import { evidenceLabels, relevanceNote } from './insight-model'
import { type CodingTask, errorText } from './model'
import { FactList, InlineError, Section, useTaskAction } from './parts'

function Toggle({ label, open, onToggle }: { label: string; onToggle: () => void; open: boolean }) {
  return (
    <Button onClick={onToggle} size="xs" variant="ghost">
      {open ? '▾' : '▸'} {label}
    </Button>
  )
}

export function WhyTheseFiles({ task }: { task: CodingTask }) {
  const [open, setOpen] = useState(false)
  const rows = task.relevance ?? []

  if (rows.length === 0) {
    return null
  }

  return (
    <div className="flex flex-col gap-1">
      <Toggle label="Why these files?" onToggle={() => setOpen(!open)} open={open} />
      {open && (
        <ul className="flex flex-col gap-1 text-xs">
          {rows.map(row => (
            <li className="rounded-[3px] border border-(--ui-stroke-secondary) px-2 py-1" key={row.path}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[0.7rem]">{row.path}</span>
                <span className="text-muted-foreground">
                  {row.score.toFixed(1)} · {relevanceNote(row)}
                </span>
              </div>
              <div className="text-[0.65rem] text-muted-foreground">{evidenceLabels(row).join(' · ')}</div>
              <div className="text-[0.65rem]">{row.reasons.join('; ')}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function IntelligenceDetails({ task }: { task: CodingTask }) {
  const [open, setOpen] = useState(false)
  const info = task.intelligence
  const memory = task.memory

  if (!info && !memory) {
    return null
  }

  const ranking = (info?.ranking ?? {}) as { components?: Record<string, number>; semantic_hits?: number }

  const semantic = (info?.semantic ?? {}) as {
    last_query_ms?: number
    provider?: string
    reason?: string
    status?: string
  }

  return (
    <div className="flex flex-col gap-1">
      <Toggle label="Intelligence details" onToggle={() => setOpen(!open)} open={open} />
      {open && (
        <FactList
          rows={[
            {
              label: 'Evidence used',
              value: Object.entries(ranking.components ?? {})
                .map(([k, v]) => `${k}: ${v}`)
                .join(', ')
            },
            {
              label: 'Semantic',
              value: `${semantic.status ?? 'off'}${semantic.provider ? ` · ${semantic.provider}` : ''} · ${ranking.semantic_hits ?? 0} hit(s)${semantic.last_query_ms ? ` · ${semantic.last_query_ms} ms` : ''}`
            },
            { label: 'Memory used', value: String(memory?.used?.length ?? 0) },
            {
              label: 'Stale memory ignored',
              value: (memory?.stale_ignored ?? []).map(s => `${s.note} (${s.why})`).join('; ') || 'none'
            },
            { label: 'Context', value: `${info?.context_items ?? 0} items, ${info?.context_chars ?? 0} chars` },
            { label: 'Repairs', value: String(info?.repairs ?? 0) },
            {
              label: 'Milestone',
              value: task.roadmap ? `${task.roadmap.milestone} of roadmap ${task.roadmap.roadmap_id.slice(0, 8)}` : '—'
            }
          ]}
        />
      )}
    </div>
  )
}

export function MemoryCandidates({ task }: { task: CodingTask }) {
  const action = useTaskAction(task.task_id)
  const client = useQueryClient()
  const finished = ['committed', 'integrated', 'integration_preview', 'integrating'].includes(task.stage)

  const candidates = useQuery({
    enabled: finished,
    queryFn: () => codingApi.memoryCandidates(task.task_id),
    queryKey: ['meu-coding', 'memory', task.task_id, task.stage]
  })

  if (!finished || !candidates.data?.length) {
    return null
  }

  const decide = (id: string, decision: 'accept' | 'dismiss') =>
    action.run(async () => {
      const result = await codingApi.memoryDecide(task.task_id, id, decision)
      void client.invalidateQueries({ queryKey: ['meu-coding', 'memory', task.task_id] })

      return result
    })

  return (
    <Section title="Remember for this project?">
      <p className="text-xs text-muted-foreground">
        Proposed notes for the project's memory. Nothing is saved unless you accept it; the current code always wins
        over a remembered note.
      </p>
      {candidates.data.map(c => (
        <div className="flex flex-col gap-1 text-xs" key={c.candidate_id}>
          <span>
            <span className="font-semibold">{c.category.replaceAll('_', ' ').toLowerCase()}</span> — {c.note}
          </span>
          <span className="text-muted-foreground">
            {c.why} (confidence {c.confidence.toFixed(2)})
          </span>
          {c.state === 'accepted' ? (
            <span className="text-muted-foreground">Saved.</span>
          ) : (
            <div className="flex gap-2">
              <Button disabled={action.pending} onClick={() => decide(c.candidate_id, 'accept')} size="xs">
                Accept
              </Button>
              <Button
                disabled={action.pending}
                onClick={() => decide(c.candidate_id, 'dismiss')}
                size="xs"
                variant="ghost"
              >
                Dismiss
              </Button>
            </div>
          )}
        </div>
      ))}
      {candidates.error && <InlineError description={errorText(candidates.error)} title="Memory unavailable" />}
      {action.error && <InlineError description={action.error} title="Not saved" />}
    </Section>
  )
}
