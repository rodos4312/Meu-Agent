/**
 * Pure view logic for the coding task page — no SDK, no React, so it is unit-tested directly.
 *
 * The backend (`meu_coding/task_views.py::snapshot`) is the authority for stage and for which
 * actions are allowed; this module only presents it. Decision params are built from the
 * approval the user is LOOKING AT (its exact id + fingerprint), never from a vague "allow".
 */

import type { CodingRemote } from './remote-model'

export type CodingStage =
  | 'analyzing'
  | 'awaiting_approval'
  | 'awaiting_keep_reject'
  | 'blocked'
  | 'coding'
  | 'committed'
  | 'executing'
  | 'failed'
  | 'integrated'
  | 'integrating'
  | 'integration_preview'
  | 'interrupted'
  | 'kept'
  | 'planning'
  | 'ready_to_commit'
  | 'rejected'
  | 'reviewing'
  | 'reviewing_diff'
  | 'testing'

export type StageTone = 'attention' | 'busy' | 'danger' | 'done' | 'muted' | 'success'

export interface CodingActions {
  approve: boolean
  create_remote_pr?: boolean
  integration_approve?: boolean
  integration_cancel?: boolean
  integration_preview?: boolean
  merge?: boolean
  pr_edit?: boolean
  pr_prepare?: boolean
  pr_create_approve?: boolean
  pr_refresh?: boolean
  push?: boolean
  push_approve?: boolean
  merge_approve?: boolean
  remote_detect?: boolean
  repair_from_feedback?: boolean
  commit_confirm: boolean
  commit_prepare: boolean
  keep: boolean
  reject: boolean
  reject_proposal: boolean
  repair: boolean
}

export interface CodingCheck {
  description: string
  kind: string
  targets: string[]
}

export interface CodingImpact {
  affected_tests: string[]
  callers: string[]
  config: string[]
  reasons: string[]
  reverse_dependencies: number
  risk: string
}

export interface CodingPlan {
  assumptions: string[]
  checks: CodingCheck[]
  files_to_change: string[]
  files_untouched: string[]
  impact: CodingImpact | null
  new_files: string[]
  protected_paths: string[]
  questions: string[]
  risk: string
  steps: string[]
  summary: string
  symbols: string[]
}

export interface CodingApproval {
  approval_id: string
  changes: string[]
  fingerprint: string
  fingerprint_short: string
  proposed_diff: string
  proposed_diff_truncated: boolean
  review_rationale: string
  strategy: string
  strategy_reason: string
  target_files: string[]
  worktree_target: { base_commit: string; branch: string; location: string; repo_root: string }
}

export interface CodingTestRun {
  check: string
  kind: string
  output: string
  seconds: number
  status: string
}

export interface CodingFinding {
  category: string
  message: string
  path: null | string
  severity: string
}

export interface CodingExecution {
  actual_diff: string
  actual_diff_truncated: boolean
  additions: number
  approval_id: string
  attempt: number
  commit_status: string
  deletions: number
  files_changed: string[]
  fingerprint: string
  impact: CodingImpact | null
  reasons: string[]
  reviewer: {
    confidence: number
    findings: CodingFinding[]
    rationale: string
    repair_instructions: string[]
    verdict: string
  }
  status: string
  tests: CodingTestRun[]
  worktree: { base_commit: string; branch: string; path: string; state: Record<string, unknown> }
}

export interface CodingCommit {
  additions?: number
  base_commit?: string
  branch?: string
  deletions?: number
  files?: string[]
  hash: string
  note?: string
  parent_branch?: string
  stat?: string
  suggested_message?: string
  token?: string
  worktree_path?: string
}

export interface CodingResult {
  additions: number
  approval_source: string
  base_commit: string
  changed_files: string[]
  deletions: number
  result_commit: string
  reviewer_rationale: string
  reviewer_verdict: string
  states: string[]
  target_branch: string
  tests: { check: string; kind?: string; status: string }[]
  worktree_branch: string
}

export interface CodingIntegrationPreview {
  base_commit: string
  changed_files: string[]
  conflicts: string[]
  diff_stat: string
  drift_commits: string[]
  drift_files: string[]
  explanation: string
  overlapping_files: string[]
  result_commit: string
  source_branch: string
  status: 'blocked' | 'clean' | 'conflict' | 'needs_rebase_or_replay'
  strategies: string[]
  target_branch: string
  target_changed: boolean
  target_head: string
}

export interface CodingIntegration {
  branch?: string
  checks?: { check: string; kind: string; status: string }[]
  final_diff?: string
  final_diff_truncated?: boolean
  final_files?: string[]
  final_stat?: string
  integration_commit?: string
  patch_changed?: boolean
  preview?: CodingIntegrationPreview
  reason?: string
  review?: { rationale: string; verdict: string }
  status: string
  target_head?: string
  token?: string
}

export interface CodingPr {
  body: string
  files: string[]
  message: string
  remote_available: boolean
  risk: string
  source_branch: string
  status: 'approved_for_later' | 'cancelled' | 'draft'
  target_branch: string
  tests: { failed: string[]; passed: number }
  title: string
}

export interface CodingRouting {
  complexity?: string
  reasons?: string[]
  route: string
  source?: string
  workload?: string
}

export interface CodingTask {
  actions: CodingActions
  approval: CodingApproval | null
  attempts: { approval_id: string; number: number; status: string; verdict: string }[]
  busy: boolean
  cleanup: { worktrees?: Record<string, unknown>[] }
  commit: CodingCommit | null
  description: string
  error: string
  execution: CodingExecution | null
  decisions?: { decision: string; device?: string; source?: string }[]
  history: string[]
  integration?: CodingIntegration | null
  models: Record<string, string>
  pr?: CodingPr | null
  result?: CodingResult | null
  routing?: Record<string, CodingRouting>
  plan: CodingPlan | null
  project: string
  remote?: CodingRemote | null
  restored: boolean
  route_source: string
  stage: CodingStage
  stage_label: string
  task_id: string
  timings: Record<string, number>
}

export interface CodingTaskRow {
  created_at: number
  description: string
  project: string
  stage: CodingStage
  task_id: string
}

/** The user-visible pipeline, in order (terminal outcomes are shown separately). */
export const PIPELINE: readonly CodingStage[] = [
  'analyzing',
  'planning',
  'coding',
  'reviewing',
  'awaiting_approval',
  'executing',
  'testing',
  'reviewing_diff',
  'awaiting_keep_reject',
  'ready_to_commit',
  'committed',
  'integration_preview',
  'integrating',
  'integrated'
]

const TONES: Record<CodingStage, StageTone> = {
  analyzing: 'busy',
  awaiting_approval: 'attention',
  awaiting_keep_reject: 'attention',
  blocked: 'danger',
  coding: 'busy',
  committed: 'success',
  executing: 'busy',
  failed: 'danger',
  integrated: 'done',
  integrating: 'busy',
  integration_preview: 'attention',
  interrupted: 'danger',
  kept: 'muted',
  planning: 'busy',
  ready_to_commit: 'success',
  rejected: 'muted',
  reviewing: 'busy',
  reviewing_diff: 'busy',
  testing: 'busy'
}

export function stageTone(stage: CodingStage): StageTone {
  return TONES[stage] ?? 'muted'
}

/** Index of the stage in PIPELINE, or -1 for an off-pipeline outcome. */
export function pipelineStep(stage: CodingStage): number {
  return PIPELINE.indexOf(stage)
}

export function shortFingerprint(fingerprint: string): string {
  return fingerprint.length > 16 ? `${fingerprint.slice(0, 8)}…${fingerprint.slice(-8)}` : fingerprint
}

export interface DecisionParams extends Record<string, unknown> {
  approval_id: string
  decision: 'approve' | 'reject'
  device: string
  fingerprint: string
  task_id: string
}

/** Params for `coding.decide`, bound to the exact approval on screen. Null when nothing is
 *  awaiting a decision — the UI must not offer a decision then. */
export function decisionParams(
  task: CodingTask,
  decision: 'approve' | 'reject',
  device: string
): DecisionParams | null {
  const approval = task.approval

  if (!approval || task.stage !== 'awaiting_approval' || !task.actions.approve) {
    return null
  }

  return {
    approval_id: approval.approval_id,
    decision,
    device,
    fingerprint: approval.fingerprint,
    task_id: task.task_id
  }
}

export interface Fact {
  label: string
  value: string
}

/** The approval card's rows: everything the user approves, in one place. */
export function approvalFacts(task: CodingTask): Fact[] {
  const plan = task.plan
  const approval = task.approval

  if (!plan || !approval) {
    return []
  }

  const list = (items: readonly string[], empty = 'none') => (items.length ? items.join(', ') : empty)
  const impact = plan.impact

  return [
    { label: 'Task', value: task.description },
    { label: 'Plan', value: plan.summary || plan.steps.join('; ') },
    { label: 'Steps', value: list(plan.steps) },
    { label: 'Target files', value: list(approval.target_files) },
    { label: 'Protected', value: list(plan.protected_paths) },
    { label: 'Kept untouched', value: list(plan.files_untouched) },
    { label: 'Edit strategy', value: `${approval.strategy} (${approval.strategy_reason})` },
    { label: 'Risk', value: plan.risk.toUpperCase() },
    {
      label: 'Impact',
      value: impact
        ? `${impact.reverse_dependencies} dependent file(s); tests: ${list(impact.affected_tests)}${
            impact.reasons.length ? `; ${impact.reasons.join('; ')}` : ''
          }`
        : 'not computed'
    },
    { label: 'Tests to run', value: list(plan.checks.map(c => `${c.kind}: ${list(c.targets, 'new test')}`)) },
    {
      label: 'Worktree',
      value: `${approval.worktree_target.location} — from ${approval.worktree_target.branch} @ ${approval.worktree_target.base_commit.slice(0, 12)}`
    },
    { label: 'Fingerprint', value: approval.fingerprint }
  ]
}

export type DiffLineKind = 'add' | 'context' | 'del' | 'hunk' | 'meta'

export interface DiffLine {
  kind: DiffLineKind
  text: string
}

export interface DiffFile {
  additions: number
  deletions: number
  lines: DiffLine[]
  path: string
}

const FILE_HEADER = /^diff --git a\/(.+?) b\/(.+)$/

function lineKind(line: string): DiffLineKind {
  if (line.startsWith('@@')) {
    return 'hunk'
  }

  if (line.startsWith('index ') || line.startsWith('new file') || line.startsWith('deleted file')) {
    return 'meta'
  }

  if (line.startsWith('+')) {
    return 'add'
  }

  if (line.startsWith('-')) {
    return 'del'
  }

  return 'context'
}

function newFile(path: string): DiffFile {
  return { additions: 0, deletions: 0, lines: [], path }
}

/** `---`/`+++` are headers only as an adjacent pair; inside a hunk they are content lines. */
function isPairedHeader(lines: readonly string[], index: number): boolean {
  const line = lines[index]

  return (
    (line.startsWith('--- ') && (lines[index + 1] ?? '').startsWith('+++ ')) ||
    (line.startsWith('+++ ') && (lines[index - 1] ?? '').startsWith('--- '))
  )
}

function addLine(file: DiffFile, line: string, header: boolean): void {
  const kind: DiffLineKind = header ? 'meta' : lineKind(line)

  if (kind === 'add') {
    file.additions += 1
  } else if (kind === 'del') {
    file.deletions += 1
  }

  if (line || kind !== 'context') {
    file.lines.push({ kind, text: line })
  }
}

/** Split a unified diff (git's, or the approval preview's `--- a/ +++ b/` form) per file. */
export function parseDiff(text: string): DiffFile[] {
  const files: DiffFile[] = []
  let current: DiffFile | null = null
  const lines = (text || '').split('\n')

  for (const [index, line] of lines.entries()) {
    const gitHeader = FILE_HEADER.exec(line)

    if (gitHeader) {
      current = newFile(gitHeader[2])
      files.push(current)

      continue
    }

    const header = isPairedHeader(lines, index)

    // Preview form has no `diff --git` line: a header pair after hunks starts the next file.
    if (header && line.startsWith('--- ') && (!current || current.lines.some(l => l.kind === 'hunk'))) {
      current = newFile(line.slice(4).replace(/^a\//, ''))
      files.push(current)
    }

    if (!current) {
      continue
    }

    if (header && line.startsWith('+++ ') && line.slice(4) !== '/dev/null') {
      current.path = line.slice(4).replace(/^b\//, '')
    }

    addLine(current, line, header)
  }

  return files
}

const INTEGRATION_TEXT: Record<CodingIntegrationPreview['status'], string> = {
  blocked: 'Blocked — integration is not possible.',
  clean: 'Clean — the target branch has not changed since the task began.',
  conflict: 'Conflict — the target branch changed the same lines. Integration is blocked.',
  needs_rebase_or_replay: 'The target branch moved. The result will be replayed onto it and re-validated.'
}

export function integrationStatusText(status: CodingIntegrationPreview['status']): string {
  return INTEGRATION_TEXT[status] ?? status
}

/** Facts shown before the user approves an integration. */
export function integrationFacts(preview: CodingIntegrationPreview): Fact[] {
  const list = (items: readonly string[]) => (items.length ? items.join(', ') : 'none')

  return [
    { label: 'Status', value: integrationStatusText(preview.status) },
    { label: 'Source', value: `${preview.source_branch} @ ${preview.result_commit.slice(0, 12)}` },
    { label: 'Target', value: `${preview.target_branch} @ ${preview.target_head.slice(0, 12)}` },
    { label: 'Task base', value: preview.base_commit.slice(0, 12) },
    {
      label: 'Target changed',
      value: preview.target_changed ? `yes — ${preview.drift_commits.length} commit(s)` : 'no'
    },
    { label: 'Changed on target', value: list(preview.drift_files) },
    {
      label: 'Possible conflicts',
      value: list(preview.conflicts.length ? preview.conflicts : preview.overlapping_files)
    },
    { label: 'Files', value: list(preview.changed_files) },
    { label: 'Diff stat', value: preview.diff_stat || 'none' },
    { label: 'Explanation', value: preview.explanation }
  ]
}

/** "Architect: Deepseek · model (source)" rows for the details view. */
export function routingFacts(task: CodingTask): Fact[] {
  const routing = task.routing ?? {}
  const rows: Fact[] = []

  for (const role of ['architect', 'coder', 'coder_simple', 'reviewer']) {
    const entry = routing[role]

    if (entry?.route) {
      rows.push({ label: role.replace('_', ' '), value: `${entry.route} (${entry.source ?? task.route_source})` })
    }
  }

  const used = routing.coder_used

  if (used?.route) {
    rows.push({
      label: 'coder used',
      value: `${used.route} — ${used.workload ?? ''} (${used.complexity ?? ''}: ${(used.reasons ?? []).join('; ')})`
    })
  }

  return rows
}

/** Actionable text for an RPC failure (the backend already words refusals for users). */
export function errorText(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error ?? '')

  return message.trim() || 'The coding service did not answer — check that Meu is running, then retry.'
}
