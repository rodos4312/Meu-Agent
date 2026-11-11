/**
 * `coding.*` gateway calls (declared in `tui_gateway/contracts/coding.py`). The backend task
 * service is the authority for stage, actions and approval integrity; these helpers only
 * carry requests. Decisions take params from `decisionParams` (exact id + fingerprint).
 */

import { host } from '@hermes/plugin-sdk'

import type { CodingTask, CodingTaskRow, DecisionParams } from './model'
import { remoteApproveParams, type RemoteKind } from './remote-model'

// Planning and execution run in the background; these calls return a snapshot quickly.
const TIMEOUT_MS = 60_000

interface TaskResult {
  task: CodingTask
}

const call = async (method: string, params: Record<string, unknown>) =>
  (await host.request<TaskResult>(method, params, TIMEOUT_MS)).task

export const codingApi = {
  start: (description: string, projectRoot: string, explicitFiles: string[]) =>
    call('coding.start', { description, explicit_files: explicitFiles, project_root: projectRoot }),
  get: (taskId: string) => call('coding.get', { task_id: taskId }),
  list: async () => (await host.request<{ tasks: CodingTaskRow[] }>('coding.list', {}, TIMEOUT_MS)).tasks,
  decide: (params: DecisionParams) => call('coding.decide', params),
  keep: (taskId: string) => call('coding.keep', { task_id: taskId }),
  reject: (taskId: string) => call('coding.reject', { task_id: taskId }),
  repair: (taskId: string) => call('coding.repair', { task_id: taskId }),
  commitPrepare: (taskId: string) => call('coding.commit.prepare', { task_id: taskId }),
  commitConfirm: (taskId: string, message: string, token: string) =>
    call('coding.commit.confirm', { confirmed: true, message, task_id: taskId, token }),
  integrationPreview: (taskId: string) => call('coding.integration.preview', { task_id: taskId }),
  integrationApprove: (taskId: string, token: string) =>
    call('coding.integration.approve', { confirmed: true, task_id: taskId, token }),
  integrationCancel: (taskId: string) => call('coding.integration.cancel', { task_id: taskId }),
  prPrepare: (taskId: string) => call('coding.pr.prepare', { task_id: taskId }),
  prUpdate: (taskId: string, changes: { body?: string; status?: string; title?: string }) =>
    call('coding.pr.update', { task_id: taskId, ...changes }),
  remoteDetect: (taskId: string) => call('coding.remote.detect', { task_id: taskId }),
  remotePreview: (taskId: string, kind: RemoteKind, extra: { body?: string; method?: string; title?: string } = {}) =>
    call('coding.remote.preview', { kind, task_id: taskId, ...extra }),
  remoteApprove: (taskId: string, kind: RemoteKind, fingerprint: string) =>
    call('coding.remote.approve', remoteApproveParams(taskId, kind, fingerprint)),
  remoteCancel: (taskId: string, kind: RemoteKind) => call('coding.remote.cancel', { kind, task_id: taskId }),
  remoteRefresh: (taskId: string) => call('coding.remote.refresh', { task_id: taskId }),
  remoteFeedback: async (taskId: string) =>
    (await host.request<{ comments: ReviewComment[] }>('coding.remote.feedback', { task_id: taskId }, TIMEOUT_MS))
      .comments,
  remoteRepair: (taskId: string, commentIds: number[]) =>
    call('coding.remote.repair', { comment_ids: commentIds, task_id: taskId })
}

export interface ReviewComment {
  author: string
  body: string
  id: number
  line: null | number
  path: string
}
