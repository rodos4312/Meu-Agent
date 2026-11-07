import type { CoordinatorPlan } from '@hermes/shared'

import { parseMaybeObject } from '@/components/assistant-ui/tool/fallback-model'
import type { SubagentProgress } from '@/store/subagents'

export type CoordinatorTaskView = CoordinatorPlan['tasks'][number]
const STATES = new Set(['pending', 'running', 'needs_review', 'verified', 'failed', 'interrupted'])
const text = (value: unknown): string | undefined => (typeof value === 'string' && value.trim() ? value : undefined)

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string').slice(0, 100) : []

/** Persisted single-call bridges retain tool_call as their outer name. */
export function coordinatorCall(toolName: string, args: Record<string, unknown>): Record<string, unknown> | null {
  if (toolName === 'coordinate_project') {return args}

  if (toolName !== 'tool_call') {return null}
  const calls = Array.isArray(args.calls) ? args.calls : [args]
  const call = parseMaybeObject(calls[0])

  return calls.length === 1 && call.name === 'coordinate_project' ? parseMaybeObject(call.arguments) : null
}

/** Display only the native checkpoint; worker completion cannot grant acceptance. */
export function coordinatorTasks(snapshot: unknown): CoordinatorTaskView[] {
  const record = parseMaybeObject(snapshot)
  const root = text(record.root)

  const rows = Array.isArray(record.progress)
    ? record.progress
    : Object.entries(parseMaybeObject(record.tasks)).map(([id, raw]) => {
        const row = parseMaybeObject(raw)
        const task = parseMaybeObject(row.task)
        const receipt = parseMaybeObject(row.result)
        const route = parseMaybeObject(receipt.route)
        const settled = ['needs_review', 'verified', 'failed'].includes(String(row.state))

        const artifacts =
          root && row.state === 'verified'
            ? Object.keys(parseMaybeObject(row.artifacts))
                .filter(name => {
                  const parts = name.replaceAll('\\', '/').split('/')

                  return !/^(?:[a-z]:|\/|\\)/i.test(name) && !parts.some(part => part === '..' || part === '.')
                })
                .map(name => ({ name, path: `${root.replace(/[\\/]$/, '')}/${name}` }))
            : []

        return {
          ...task,
          id,
          state: row.state,
          attempt: row.attempt,
          evidence: row.evidence,
          error: row.error,
          repair_check: parseMaybeObject(row.repair).check,
          artifacts,
          provider: settled ? route.provider : undefined,
          model: settled ? (route.model ?? receipt.model) : undefined
        }
      })

  return rows.slice(0, 100).flatMap(raw => {
    const row = parseMaybeObject(raw)
    const id = text(row.id)

    if (!id) {
      return []
    }

    const state = typeof row.state === 'string' && STATES.has(row.state) ? row.state : 'unknown'
    const review = parseMaybeObject(row.review)
    const verdict = text(review.verdict)
    const settled = ['needs_review', 'verified', 'failed'].includes(state)

    return [
      {
        id,
        goal: text(row.goal) || id,
        state,
        attempt:
          typeof row.attempt === 'number' && Number.isSafeInteger(row.attempt) && row.attempt > 0 ? row.attempt : 0,
        acceptance: text(row.acceptance),
        workload: text(row.workload),
        depends_on: strings(row.depends_on),
        review_of: text(row.review_of),
        evidence: settled ? text(row.evidence) : undefined,
        error: text(row.error),
        repair_check: text(row.repair_check),
        provider: settled ? text(row.provider) : undefined,
        model: settled ? text(row.model) : undefined,
        review:
          (state === 'needs_review' || state === 'verified') &&
          verdict &&
          ['pass', 'needs_fix', 'inconclusive'].includes(verdict) &&
          text(review.check) &&
          text(review.observed) &&
          Number.isSafeInteger(review.reviewed_attempt) &&
          Number(review.reviewed_attempt) > 0
            ? {
                verdict,
                check: text(review.check),
                observed: text(review.observed),
                reviewed_attempt: Number(review.reviewed_attempt)
              }
            : undefined,
        artifacts:
          state === 'verified' && Array.isArray(row.artifacts)
            ? row.artifacts.flatMap(rawFile => {
                const file = parseMaybeObject(rawFile)

                return text(file.name) && text(file.path) ? [{ name: String(file.name), path: String(file.path) }] : []
              })
            : []
      }
    ]
  })
}

/** An exact native dispatch ID is required; matching a goal alone steals other runs. */
export function coordinatorLiveModel(
  task: CoordinatorTaskView,
  snapshot: unknown,
  live: readonly SubagentProgress[]
): string | undefined {
  if (task.state !== 'running') {
    return undefined
  }

  const dispatch = parseMaybeObject(parseMaybeObject(snapshot).dispatch)
  const ids = dispatch.subagent_ids
  const goals = dispatch.goals

  if (!Array.isArray(goals) || goals.length > 100 || !goals.every(goal => typeof goal === 'string')) {
    return undefined
  }

  if (!Array.isArray(ids) || ids.length !== goals.length || !ids.every(id => typeof id === 'string')) {
    return undefined
  }

  const indices = goals.flatMap((goal, index) => (goal === task.goal ? [index] : []))

  if (indices.length !== 1) {
    return undefined
  }

  const index = indices[0]

  const match = live.find(
    child =>
      (ids[index] && child.id === ids[index]) ||
      (text(dispatch.delegation_id) && child.delegationId === dispatch.delegation_id && child.taskIndex === index)
  )

  return match?.model
}
