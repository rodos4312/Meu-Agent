/**
 * `coding.*` gateway calls (declared in `tui_gateway/contracts/coding.py`). The backend task
 * service is the authority for stage, actions and approval integrity; these helpers only
 * carry requests. Decisions take params from `decisionParams` (exact id + fingerprint).
 */

import { host } from '@hermes/plugin-sdk'

import type { CodingTask, CodingTaskRow, DecisionParams } from './model'

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
    call('coding.commit.confirm', { confirmed: true, message, task_id: taskId, token })
}
