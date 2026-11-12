/**
 * Planner roadmaps: a broad goal becomes milestones; the user approves ONE ready milestone at a
 * time (it then runs as a normal coding task with its own approval), rejects, edits, pauses, and
 * accepts or declines the planner's proposed revisions. There is no "approve all".
 */

import { atom, Badge, Button, host, Input, Textarea, useQuery, useQueryClient, useValue } from '@hermes/plugin-sdk'
import { useState } from 'react'

import { roadmapApi } from './api'
import {
  editableMilestone,
  type Milestone,
  MILESTONE_TONE,
  milestoneApproveParams,
  type Roadmap
} from './insight-model'
import { errorText } from './model'
import { FactList, InlineError, Section } from './parts'

export const $selectedRoadmap = atom<null | string>(null)
const ROADMAP_KEY = (id: string) => ['meu-coding', 'roadmap', id]
const ROADMAPS_KEY = ['meu-coding', 'roadmaps']

const TONE_BADGE = { danger: 'destructive', done: 'solid', muted: 'muted', progress: 'default', ready: 'warn' } as const

function useRoadmapAction(roadmapId: string) {
  const client = useQueryClient()
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)

  const run = async (fn: () => Promise<Roadmap>) => {
    setPending(true)

    try {
      client.setQueryData(ROADMAP_KEY(roadmapId), await fn())
      setError('')
      void client.invalidateQueries({ queryKey: ROADMAPS_KEY })
      void client.invalidateQueries({ queryKey: ['meu-coding', 'tasks'] })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setPending(false)
    }
  }

  return { error, pending, run }
}

function MilestoneCard({ milestone, roadmap }: { milestone: Milestone; roadmap: Roadmap }) {
  const action = useRoadmapAction(roadmap.roadmap_id)
  const [confirmed, setConfirmed] = useState(false)
  const approvable = roadmap.actions.approve.includes(milestone.id)
  const rejectable = roadmap.actions.reject.includes(milestone.id)

  return (
    <li className="flex flex-col gap-1 rounded-[3px] border border-(--ui-stroke-secondary) p-2">
      <div className="flex items-center gap-2">
        <Badge size="xs" variant={TONE_BADGE[MILESTONE_TONE[milestone.status]]}>
          {milestone.status.replaceAll('_', ' ')}
        </Badge>
        <span className="text-xs font-semibold">
          {milestone.id} · {milestone.title}
        </span>
      </div>
      <FactList
        rows={[
          { label: 'Objective', value: milestone.objective },
          { label: 'Depends on', value: milestone.depends_on.join(', ') || '—' },
          { label: 'Areas', value: milestone.expected_areas.join(', ') || '—' },
          { label: 'Acceptance', value: milestone.acceptance_criteria.join('; ') || '—' },
          { label: 'Tests', value: milestone.tests.join('; ') || '—' },
          { label: 'Risk / size', value: `${milestone.risk} · ${milestone.complexity} · ${milestone.kind}` },
          { label: 'Status note', value: milestone.note || milestone.outcome || '—' },
          { label: 'Fingerprint', value: milestone.fingerprint.slice(0, 16) }
        ]}
      />
      {approvable && (
        <label className="flex items-center gap-2 text-xs">
          <input checked={confirmed} onChange={event => setConfirmed(event.target.checked)} type="checkbox" />
          Start this milestone as a coding task. Its proposal still needs your approval before anything changes.
        </label>
      )}
      <div className="flex gap-2">
        {approvable && (
          <Button
            disabled={action.pending || !confirmed}
            onClick={() => action.run(() => roadmapApi.approve(milestoneApproveParams(roadmap, milestone)))}
            size="xs"
          >
            Approve milestone
          </Button>
        )}
        {rejectable && (
          <Button
            disabled={action.pending}
            onClick={() => action.run(() => roadmapApi.reject(roadmap.roadmap_id, milestone.id))}
            size="xs"
            variant="ghost"
          >
            Reject milestone
          </Button>
        )}
      </div>
      {action.error && <InlineError description={action.error} title="Refused" />}
    </li>
  )
}

function RevisionCard({ roadmap }: { roadmap: Roadmap }) {
  const action = useRoadmapAction(roadmap.roadmap_id)
  const revision = roadmap.pending_revision

  if (!revision) {
    return null
  }

  return (
    <Section title="Planner proposes a roadmap change">
      <p className="text-xs">{revision.reason}</p>
      <FactList
        rows={[
          { label: 'Operations', value: revision.operations.map(o => `${o.op} ${o.milestone ?? ''}`).join('; ') },
          { label: 'Scope changes', value: revision.scope_expansion.join('; ') || 'none' },
          { label: 'New milestones', value: revision.milestones.map(m => `${m.id} ${m.title}`).join('; ') }
        ]}
      />
      <div className="flex gap-2">
        <Button
          disabled={action.pending}
          onClick={() => action.run(() => roadmapApi.revision(roadmap.roadmap_id, revision.revision_id, 'accept'))}
          size="xs"
        >
          Accept change
        </Button>
        <Button
          disabled={action.pending}
          onClick={() => action.run(() => roadmapApi.revision(roadmap.roadmap_id, revision.revision_id, 'decline'))}
          size="xs"
          variant="ghost"
        >
          Keep current roadmap
        </Button>
      </div>
      {action.error && <InlineError description={action.error} title="Refused" />}
    </Section>
  )
}

function RoadmapEditor({ roadmap, onDone }: { onDone: () => void; roadmap: Roadmap }) {
  const action = useRoadmapAction(roadmap.roadmap_id)
  const [text, setText] = useState(() => JSON.stringify(roadmap.milestones.map(editableMilestone), null, 2))

  const save = () =>
    action.run(async () => {
      const parsed = JSON.parse(text) as Record<string, unknown>[]
      const result = await roadmapApi.edit(roadmap.roadmap_id, roadmap.revision, parsed)
      onDone()

      return result
    })

  return (
    <Section title="Edit roadmap">
      <p className="text-xs text-muted-foreground">
        Approved, running and finished milestones cannot change. Saving creates a new roadmap revision.
      </p>
      <Textarea className="min-h-64 font-mono text-[0.65rem]" onChange={e => setText(e.target.value)} value={text} />
      <div className="flex gap-2">
        <Button disabled={action.pending} onClick={save} size="xs">
          Save roadmap
        </Button>
        <Button onClick={onDone} size="xs" variant="ghost">
          Cancel
        </Button>
      </div>
      {action.error && <InlineError description={action.error} title="Not saved" />}
    </Section>
  )
}

export function RoadmapDetail({ roadmapId }: { roadmapId: string }) {
  const [editing, setEditing] = useState(false)
  const action = useRoadmapAction(roadmapId)

  const { data: roadmap, error } = useQuery({
    queryFn: () => roadmapApi.get(roadmapId),
    queryKey: ROADMAP_KEY(roadmapId),
    refetchInterval: query => {
      const status = (query.state.data as Roadmap | undefined)?.status

      return status === 'planning' || status === 'active' ? 3_000 : false
    }
  })

  if (error) {
    return <InlineError description={errorText(error)} title="Roadmap unavailable" />
  }

  if (!roadmap) {
    return <p className="text-xs text-muted-foreground">Loading…</p>
  }

  const a = roadmap.actions
  const deferred = (roadmap.context_summary.deferred_work as string[] | undefined) ?? []

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Badge variant="muted">{roadmap.status.replaceAll('_', ' ')}</Badge>
        <span className="text-sm">{roadmap.goal}</span>
      </div>
      {roadmap.status === 'planning' && <p className="text-xs text-muted-foreground">Planning (read-only)…</p>}
      {roadmap.error && <InlineError description={roadmap.error} title="Planner" />}
      {deferred.length > 0 && (
        <p className="text-xs text-muted-foreground">Kept out of this roadmap (deferred): {deferred.join(' · ')}</p>
      )}
      <div className="flex flex-wrap gap-2">
        {a.edit && !editing && (
          <Button onClick={() => setEditing(true)} size="xs" variant="outline">
            Edit roadmap
          </Button>
        )}
        {(a.pause || a.resume) && (
          <Button
            disabled={action.pending}
            onClick={() => action.run(() => roadmapApi.pause(roadmapId, a.pause))}
            size="xs"
            variant="outline"
          >
            {a.pause ? 'Pause' : 'Resume'}
          </Button>
        )}
        {a.replan && (
          <Button disabled={action.pending} onClick={() => action.run(() => roadmapApi.replan(roadmapId))} size="xs">
            Plan again
          </Button>
        )}
      </div>
      {action.error && <InlineError description={action.error} title="Refused" />}
      {editing && <RoadmapEditor onDone={() => setEditing(false)} roadmap={roadmap} />}
      <RevisionCard roadmap={roadmap} />
      <ul className="flex flex-col gap-2">
        {roadmap.milestones.map(m => (
          <MilestoneCard key={`${m.id}-${m.fingerprint}`} milestone={m} roadmap={roadmap} />
        ))}
      </ul>
    </div>
  )
}

export function RoadmapList() {
  const cwd = useValue(host.state.cwd)
  const selected = useValue($selectedRoadmap)
  const client = useQueryClient()
  const [goal, setGoal] = useState('')
  const [error, setError] = useState('')
  const { data: rows = [] } = useQuery({ queryFn: roadmapApi.list, queryKey: ROADMAPS_KEY, refetchInterval: 10_000 })

  const create = async () => {
    try {
      const roadmap = await roadmapApi.create(goal, cwd ?? '')
      setGoal('')
      setError('')
      $selectedRoadmap.set(roadmap.roadmap_id)
      void client.invalidateQueries({ queryKey: ROADMAPS_KEY })
    } catch (err) {
      setError(errorText(err))
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <Input
        onChange={e => setGoal(e.target.value)}
        placeholder="Broad goal, e.g. improve sync reliability"
        value={goal}
      />
      <Button disabled={!goal.trim() || !cwd} onClick={() => void create()} size="xs">
        Plan roadmap
      </Button>
      {error && <InlineError description={error} title="Planner" />}
      <ul className="flex flex-col gap-1">
        {rows.map(row => (
          <li key={row.roadmap_id}>
            <button
              className={`w-full rounded-[3px] px-2 py-1 text-left text-xs hover:bg-muted ${selected === row.roadmap_id ? 'bg-muted' : ''}`}
              onClick={() => $selectedRoadmap.set(row.roadmap_id)}
              type="button"
            >
              <Badge size="xs" variant="muted">
                {row.status.replaceAll('_', ' ')}
              </Badge>{' '}
              <span className="line-clamp-2">{row.goal}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
