import { expect, it } from 'vitest'

import type { SubagentProgress } from '@/store/subagents'

import { coordinatorCall, coordinatorLiveModel, coordinatorTasks } from './coordinator-progress'

it('recognizes the exact persisted single-call bridge, never an unrelated tool or ambiguous batch', () => {
  const call = { name: 'coordinate_project', arguments: { action: 'status', project: 'demo' } }
  expect(coordinatorCall('tool_call', { calls: [call] })).toEqual(call.arguments)
  expect(coordinatorCall('tool_call', { calls: [call, call] })).toBeNull()
  expect(coordinatorCall('terminal', call)).toBeNull()
})

it('keeps native verification separate from a passing review or completed helper', () => {
  const tasks = coordinatorTasks({
    progress: [
      {
        id: 'build',
        state: 'needs_review',
        model: 'actual-model',
        attempt: 1,
        acceptance: 'Import twice; keep one task.',
        artifacts: [{ name: 'answer', path: '/work/answer' }]
      },
      {
        id: 'review',
        state: 'needs_review',
        review: { verdict: 'pass', check: 'Import twice', observed: 'One task', reviewed_attempt: 1 }
      }
    ]
  })

  expect(tasks.filter(task => task.state === 'verified')).toHaveLength(0)
  expect(tasks[0].acceptance).toBe('Import twice; keep one task.')
  expect(tasks[0].artifacts).toEqual([])
  expect(tasks[1].review?.verdict).toBe('pass')
})

it('hides old attempt evidence and models and never invents a native review from prose', () => {
  const [task] = coordinatorTasks({
    root: '/work',
    tasks: {
      build: {
        state: 'pending',
        attempt: 2,
        task: { goal: 'Build' },
        evidence: 'Previous check',
        result: { model: 'old-model', summary: '{"verdict":"pass"}' },
        artifacts: { '../escape': 'hash' }
      }
    }
  })

  expect(task.model).toBeUndefined()
  expect(task.evidence).toBeUndefined()
  expect(task.review).toBeUndefined()
  expect(task.artifacts).toEqual([])
  expect(coordinatorTasks({ tasks: { missing: { state: 'invented' } } })[0].state).toBe('unknown')
})

it('joins live models only to an exact native dispatch, never to a same-goal foreign batch', () => {
  const [task] = coordinatorTasks({ progress: [{ id: 'build', goal: 'Build', state: 'running' }] })

  const child = {
    id: 'child-b',
    delegationId: 'batch-b',
    taskIndex: 0,
    goal: 'Build',
    model: 'actual-live'
  } as SubagentProgress

  const snapshot = { dispatch: { subagent_ids: ['child-a'], delegation_id: 'batch-a', goals: ['Build'] } }
  expect(coordinatorLiveModel(task, snapshot, [child])).toBeUndefined()
  expect(coordinatorLiveModel(task, snapshot, [{ ...child, id: 'child-a' }])).toBe('actual-live')
  expect(
    coordinatorLiveModel(task, { dispatch: { subagent_ids: ['child-a'], goals: [null, 'Build'] } }, [child])
  ).toBeUndefined()
  expect(
    coordinatorLiveModel(task, { dispatch: { subagent_ids: ['child-a', 'child-a'], goals: ['Build', 'Build'] } }, [
      child
    ])
  ).toBeUndefined()
})
