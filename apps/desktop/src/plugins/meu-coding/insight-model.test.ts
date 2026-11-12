import { describe, expect, it } from 'vitest'

import {
  editableMilestone,
  evidenceLabels,
  type Milestone,
  milestoneApproveParams,
  relevanceNote,
  type RelevanceRow,
  type Roadmap
} from './insight-model'

const row = (over: Partial<RelevanceRow> = {}): RelevanceRow => ({
  components: { semantic_embedding: 9.5, symbol_match: 45 },
  discovery_only: false,
  edit_target: false,
  path: 'a.py',
  reasons: ['defines symbol f'],
  score: 54.5,
  ...over
})

const milestone = (over: Partial<Milestone> = {}): Milestone => ({
  acceptance_criteria: ['works'],
  complexity: 'complex',
  depends_on: [],
  expected_areas: ['gateway/'],
  fingerprint: 'f'.repeat(64),
  id: 'm1',
  kind: 'analysis',
  note: '',
  objective: 'analyze',
  outcome: '',
  risk: 'low',
  status: 'READY',
  task_id: '',
  tests: [],
  title: 'Analyze',
  ...over
})

const roadmap = (m: Milestone, approve: string[] = [m.id]): Roadmap => ({
  actions: { approve, decide_revision: false, edit: true, pause: true, reject: [], replan: false, resume: false },
  context_summary: {},
  error: '',
  goal: 'goal',
  milestones: [m],
  pending_revision: null,
  project_root: '/p',
  revision: 3,
  roadmap_id: 'r'.repeat(32),
  status: 'active'
})

describe('evidenceLabels', () => {
  it('lists structural evidence before weaker semantic evidence', () => {
    expect(evidenceLabels(row())).toEqual(['exact symbol 45.0', 'semantic similarity 9.5'])
  })
})

describe('relevanceNote', () => {
  it('marks discovery-only files as context that is never an edit target', () => {
    expect(relevanceNote(row({ discovery_only: true }))).toMatch(/never an edit target/)
    expect(relevanceNote(row({ edit_target: true }))).toBe('planned edit')
  })
})

describe('milestoneApproveParams', () => {
  it('binds exactly one milestone with its fingerprint and the roadmap revision', () => {
    const m = milestone()
    expect(milestoneApproveParams(roadmap(m), m)).toEqual({
      confirmed: true,
      fingerprint: m.fingerprint,
      milestone_id: 'm1',
      revision: 3,
      roadmap_id: 'r'.repeat(32)
    })
  })

  it('refuses a milestone the backend has not marked approvable', () => {
    const planned = milestone({ status: 'PLANNED' })
    expect(() => milestoneApproveParams(roadmap(planned, []), planned)).toThrow(/not ready/)
    const ready = milestone()
    expect(() => milestoneApproveParams(roadmap(ready, []), ready)).toThrow(/not ready/)
  })
})

describe('editableMilestone', () => {
  it('drops status and task fields so an edit cannot forge them', () => {
    const edit = editableMilestone(milestone({ status: 'DONE', task_id: 'x' }))
    expect(edit).not.toHaveProperty('status')
    expect(edit).not.toHaveProperty('task_id')
    expect(edit).not.toHaveProperty('fingerprint')
  })
})
