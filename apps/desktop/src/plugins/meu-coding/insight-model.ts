/**
 * Pure view logic for Phase 7: "Why these files?", memory candidates and the planner roadmap.
 * The backend owns ranking, memory and milestone state; this only presents it. A milestone
 * approval is built from the milestone the user is LOOKING AT (its id, fingerprint and the
 * roadmap revision), one milestone at a time.
 */

export interface RelevanceRow {
  components: Record<string, number>
  discovery_only: boolean
  edit_target: boolean
  path: string
  reasons: string[]
  score: number
}

const EVIDENCE_LABELS: Record<string, string> = {
  dependency_proximity: 'dependency',
  memory: 'memory',
  path_file_match: 'path / keyword',
  recent_change: 'recent change',
  semantic_embedding: 'semantic similarity',
  structural_graph: 'graph',
  symbol_match: 'exact symbol',
  test_relation: 'related test'
}

/** Evidence labels, strongest first (structural before discovery signals). */
export function evidenceLabels(row: RelevanceRow): string[] {
  return Object.entries(row.components)
    .sort(([a, x], [b, y]) => y - x || a.localeCompare(b))
    .map(([name, points]) => `${EVIDENCE_LABELS[name] ?? name} ${points.toFixed(1)}`)
}

export function relevanceNote(row: RelevanceRow): string {
  if (row.edit_target) {
    return 'planned edit'
  }

  return row.discovery_only ? 'context only (found by similarity or memory — never an edit target)' : 'context'
}

export interface MemoryCandidate {
  candidate_id: string
  category: string
  confidence: number
  entry: string
  note: string
  state: 'accepted' | 'proposed'
  why: string
}

export type MilestoneStatus = 'APPROVED' | 'BLOCKED' | 'DONE' | 'IN_PROGRESS' | 'PLANNED' | 'READY' | 'REJECTED'

export interface Milestone {
  acceptance_criteria: string[]
  complexity: string
  depends_on: string[]
  expected_areas: string[]
  fingerprint: string
  id: string
  kind: string
  note: string
  objective: string
  outcome: string
  risk: string
  status: MilestoneStatus
  task_id: string
  tests: string[]
  title: string
}

export interface RoadmapRevision {
  material: boolean
  milestones: Milestone[]
  operations: Record<string, string>[]
  reason: string
  revision_id: string
  scope_expansion: string[]
}

export interface Roadmap {
  actions: {
    approve: string[]
    decide_revision: boolean
    edit: boolean
    pause: boolean
    reject: string[]
    replan: boolean
    resume: boolean
  }
  context_summary: Record<string, unknown>
  error: string
  goal: string
  milestones: Milestone[]
  pending_revision: null | RoadmapRevision
  project_root: string
  revision: number
  roadmap_id: string
  status: string
}

export interface RoadmapRow {
  counts: Record<string, number>
  goal: string
  milestones: number
  roadmap_id: string
  status: string
}

export interface MilestoneApproveParams extends Record<string, unknown> {
  confirmed: true
  fingerprint: string
  milestone_id: string
  revision: number
  roadmap_id: string
}

/** Exactly one milestone; refuses anything the backend has not marked approvable. */
export function milestoneApproveParams(roadmap: Roadmap, milestone: Milestone): MilestoneApproveParams {
  if (!roadmap.actions.approve.includes(milestone.id) || milestone.status !== 'READY') {
    throw new Error('This milestone is not ready for approval.')
  }

  return {
    confirmed: true,
    fingerprint: milestone.fingerprint,
    milestone_id: milestone.id,
    revision: roadmap.revision,
    roadmap_id: roadmap.roadmap_id
  }
}

export const MILESTONE_TONE: Record<MilestoneStatus, 'danger' | 'done' | 'muted' | 'progress' | 'ready'> = {
  APPROVED: 'progress',
  BLOCKED: 'danger',
  DONE: 'done',
  IN_PROGRESS: 'progress',
  PLANNED: 'muted',
  READY: 'ready',
  REJECTED: 'muted'
}

/** The editable part of a milestone, as the backend's roadmap.edit expects it. */
export function editableMilestone(m: Milestone): Record<string, unknown> {
  return {
    acceptance_criteria: m.acceptance_criteria,
    complexity: m.complexity,
    depends_on: m.depends_on,
    expected_areas: m.expected_areas,
    id: m.id,
    kind: m.kind,
    objective: m.objective,
    risk: m.risk,
    tests: m.tests,
    title: m.title
  }
}
