/**
 * Pure view logic for the REMOTE section (push → PR → merge). The backend
 * (`meu_coding/task_views.py::_remote`) owns state and which actions are allowed; this module
 * only presents it. Approvals are built from the preview the user is LOOKING AT: its kind and
 * exact fingerprint, nothing else.
 */

import type { Fact } from './model'

export type RemoteKind = 'merge' | 'pr' | 'push'

export interface RemoteInfo {
  auth_available: boolean
  available: boolean
  default_branch: string
  identity: string
  is_github: boolean
  merge_methods: string[]
  name: string
  reason: string
  url: string
}

export interface PushPreview {
  changed_files: string[]
  destination_branch: string
  expected_remote_sha: string
  fingerprint: string
  force: string
  force_required: boolean
  new_sha: string
  reason: string
  refspec: string
  remote: string
  remote_exists: boolean
  remote_url: string
  repository: string
  risk: string
  source_branch: string
  source_commit: string
  status: 'blocked' | 'ready'
  target_branch: string
  tests: { check: string; status: string }[]
}

export interface PrPreview {
  body: string
  body_hash: string
  changed_files: string[]
  commits: string[]
  fingerprint: string
  limitations: string[]
  repository: string
  risk: string
  source_branch: string
  source_sha: string
  target_branch: string
  target_sha: string
  title: string
}

export interface ChecksSummary {
  failed?: number
  pending?: number
  state: 'failing' | 'none' | 'passing' | 'pending'
  total?: number
}

export interface ReviewsSummary {
  approvals: number
  changes_requested: number
  reviewers: string[]
}

export interface MergePreview {
  allowed_methods: string[]
  checks: ChecksSummary
  changed_files: string[]
  conflicts: boolean
  fingerprint: string
  method: string
  pr_number: number
  reasons: string[]
  repository: string
  reviewer: string
  reviews: ReviewsSummary
  risk: string
  source_sha: string
  status: 'blocked' | 'clean' | 'conflict' | 'revalidation_required'
  target_branch: string
  target_drift: boolean
  target_sha: string
}

export interface PrStatus {
  checks: ChecksSummary
  draft: boolean
  head_drift: boolean
  mergeable: boolean | null
  merged: boolean
  number: number
  refreshed_at?: number
  reviews: ReviewsSummary
  state: string
  target_drift: boolean
  url: string
}

export interface CodingRemote {
  blocked?: { kind: RemoteKind; reason: string }
  events: { at: number; event: string; source?: string }[]
  info?: RemoteInfo
  merge_preview?: MergePreview
  merged?: { merge_commit_sha: string; method: string; target_verified: boolean }
  pending: RemoteKind[]
  pr?: { number: number; source_sha: string; url: string }
  pr_preview?: PrPreview
  pr_status?: PrStatus
  push_preview?: PushPreview
  pushed?: { destination_branch: string; remote: string; remote_sha: string }
  state: string
  state_label: string
}

export interface RemoteApproveParams extends Record<string, unknown> {
  confirmed: true
  fingerprint: string
  kind: RemoteKind
  task_id: string
}

const short = (sha: string | undefined) => (sha ? sha.slice(0, 12) : '—')

/** Params naming the exact preview on screen; refuses a missing or malformed fingerprint. */
export function remoteApproveParams(taskId: string, kind: RemoteKind, fingerprint: string): RemoteApproveParams {
  if (!/^[0-9a-f]{64}$/.test(fingerprint)) {
    throw new Error('No preview fingerprint to approve — preview again.')
  }

  return { confirmed: true, fingerprint, kind, task_id: taskId }
}

export function pushFacts(preview: PushPreview): Fact[] {
  return [
    { label: 'Repository', value: preview.repository },
    { label: 'Remote', value: `${preview.remote} (${preview.remote_url})` },
    { label: 'Source', value: `${preview.source_branch} @ ${short(preview.source_commit)}` },
    { label: 'Destination', value: preview.destination_branch },
    {
      label: 'Remote branch',
      value: preview.remote_exists ? `exists @ ${short(preview.expected_remote_sha)}` : 'new branch'
    },
    { label: 'Refspec', value: preview.refspec },
    { label: 'Force push', value: preview.force_required ? 'REQUIRED — forbidden, push blocked' : 'FORBIDDEN' },
    { label: 'Files', value: preview.changed_files.join(', ') },
    { label: 'Tests', value: preview.tests.map(t => `${t.check}: ${t.status}`).join('; ') || 'none recorded' },
    { label: 'Risk', value: preview.risk.toUpperCase() },
    { label: 'Target branch', value: `${preview.target_branch} — not pushed to` },
    { label: 'Fingerprint', value: preview.fingerprint.slice(0, 16) }
  ]
}

export function prFacts(preview: PrPreview): Fact[] {
  return [
    { label: 'Repository', value: preview.repository },
    { label: 'Head', value: `${preview.source_branch} @ ${short(preview.source_sha)}` },
    { label: 'Base', value: `${preview.target_branch} @ ${short(preview.target_sha)}` },
    { label: 'Commits', value: preview.commits.join('; ') || '—' },
    { label: 'Files', value: preview.changed_files.join(', ') },
    { label: 'Risk', value: preview.risk.toUpperCase() },
    { label: 'Fingerprint', value: preview.fingerprint.slice(0, 16) }
  ]
}

const checksText = (checks: ChecksSummary) =>
  checks.state === 'none'
    ? 'no checks reported'
    : `${checks.state}${checks.total ? ` (${checks.total} total, ${checks.failed ?? 0} failed, ${checks.pending ?? 0} pending)` : ''}`

const reviewsText = (reviews: ReviewsSummary) =>
  `${reviews.approvals} approval(s), ${reviews.changes_requested} change request(s)`

export function prStatusFacts(status: PrStatus): Fact[] {
  return [
    { label: 'State', value: `${status.state}${status.draft ? ' (draft)' : ''}${status.merged ? ' — merged' : ''}` },
    { label: 'Checks', value: checksText(status.checks) },
    { label: 'Reviews', value: reviewsText(status.reviews) },
    {
      label: 'Mergeable',
      value: status.mergeable === null ? 'unknown (GitHub is computing)' : String(status.mergeable)
    },
    { label: 'Head drift', value: status.head_drift ? 'YES — new commits after review' : 'no' },
    { label: 'Target drift', value: status.target_drift ? 'YES — target moved since review' : 'no' }
  ]
}

export const MERGE_STATUS_TEXT: Record<MergePreview['status'], string> = {
  blocked: 'Blocked',
  clean: 'Clean — ready to merge after your approval',
  conflict: 'Conflict — resolve on GitHub first',
  revalidation_required: 'Revalidation required — the target moved'
}

export function mergeFacts(preview: MergePreview): Fact[] {
  return [
    { label: 'Repository', value: preview.repository },
    { label: 'Pull request', value: `#${preview.pr_number}` },
    { label: 'Status', value: MERGE_STATUS_TEXT[preview.status] },
    { label: 'Head', value: short(preview.source_sha) },
    { label: 'Target', value: `${preview.target_branch} @ ${short(preview.target_sha)}` },
    { label: 'Method', value: `${preview.method} (allowed: ${preview.allowed_methods.join(', ') || 'none'})` },
    { label: 'Checks', value: checksText(preview.checks) },
    { label: 'Reviews', value: reviewsText(preview.reviews) },
    { label: 'Meu Reviewer', value: preview.reviewer.toUpperCase() },
    { label: 'Risk', value: preview.risk.toUpperCase() },
    { label: 'Files', value: preview.changed_files.join(', ') },
    { label: 'Fingerprint', value: preview.fingerprint.slice(0, 16) }
  ]
}
