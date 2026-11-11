/**
 * The Coding page (`/coding`): start a task on the current workspace, review the exact
 * fingerprinted proposal, approve or reject it, inspect the ACTUAL diff and test results from
 * the isolated worktree, keep or reject the result, and optionally commit locally on the
 * worktree branch after an explicit confirmation. Everything shown comes from the backend
 * task snapshot; nothing is recomputed here.
 */

import {
  atom,
  Badge,
  Button,
  cn,
  host,
  Input,
  Textarea,
  useMutation,
  useQuery,
  useQueryClient,
  useValue
} from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'

import { codingApi } from './api'
import {
  approvalFacts,
  type CodingIntegration,
  type CodingIntegrationPreview,
  type CodingResult,
  type CodingTask,
  decisionParams,
  type DiffFile,
  errorText,
  integrationFacts,
  parseDiff,
  PIPELINE,
  pipelineStep,
  routingFacts,
  shortFingerprint,
  type StageTone,
  stageTone
} from './model'
import { FactList, InlineError, LIST_KEY, Section, TASK_KEY, useTaskAction } from './parts'
import { RemoteSection } from './remote'

// The selected task survives navigation (module state) and a window reload (remembered id).
// Selecting never restarts anything: the backend owns the task; an id this backend does not
// know (another profile, a pruned task) is dropped by TaskDetail.
const SELECTED_KEY = 'hermes.plugin.meu-coding.selected-task'

function rememberedTask(): null | string {
  try {
    return window.localStorage.getItem(SELECTED_KEY)
  } catch {
    return null
  }
}

export const $selectedCodingTask = atom<null | string>(rememberedTask())

$selectedCodingTask.subscribe(id => {
  try {
    if (id) {
      window.localStorage.setItem(SELECTED_KEY, id)
    } else {
      window.localStorage.removeItem(SELECTED_KEY)
    }
  } catch {
    // Storage unavailable: selection stays in memory for this window only.
  }
})

const DEVICE = 'desktop'

const BADGE: Record<StageTone, 'default' | 'destructive' | 'muted' | 'solid' | 'success' | 'warn'> = {
  attention: 'warn',
  busy: 'default',
  danger: 'destructive',
  done: 'solid',
  muted: 'muted',
  success: 'success'
}

const LINE_CLASS = {
  add: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  context: 'text-foreground/80',
  del: 'bg-destructive/10 text-destructive',
  hunk: 'text-sky-600 dark:text-sky-300',
  meta: 'text-muted-foreground'
}

function DiffView({ label, text, truncated }: { label: string; text: string; truncated: boolean }) {
  const files: DiffFile[] = parseDiff(text)

  return (
    <Section title={label}>
      {files.length === 0 ? (
        <p className="text-xs text-muted-foreground">No changes.</p>
      ) : (
        files.map(file => (
          <div
            className="overflow-hidden rounded-[3px] border border-(--ui-stroke-secondary)"
            key={`${label}-${file.path}`}
          >
            <div className="flex items-center justify-between bg-muted px-2 py-1 font-mono text-[0.7rem]">
              <span>{file.path}</span>
              <span>
                <span className="text-emerald-600">+{file.additions}</span>{' '}
                <span className="text-destructive">−{file.deletions}</span>
              </span>
            </div>
            <pre className="max-h-96 overflow-auto px-2 py-1 font-mono text-[0.7rem] leading-4">
              {file.lines.map((line, index) => (
                <div className={LINE_CLASS[line.kind]} key={index}>
                  {line.text || ' '}
                </div>
              ))}
            </pre>
          </div>
        ))
      )}
      {truncated && <p className="text-xs text-muted-foreground">Diff truncated for display.</p>}
    </Section>
  )
}

function Pipeline({ task }: { task: CodingTask }) {
  const step = pipelineStep(task.stage)

  return (
    <ol className="flex flex-wrap gap-1 text-[0.6rem]">
      {PIPELINE.map((stage, index) => (
        <li
          className={cn(
            'rounded-[2px] px-1 py-px',
            index < step && 'bg-muted text-muted-foreground',
            index === step && 'bg-primary text-primary-foreground',
            (index > step || step === -1) && 'text-muted-foreground/60'
          )}
          key={stage}
        >
          {stage.replaceAll('_', ' ')}
        </li>
      ))}
    </ol>
  )
}

function ApprovalCard({ task }: { task: CodingTask }) {
  const action = useTaskAction(task.task_id)
  const [details, setDetails] = useState(false)
  const approval = task.approval

  if (!approval) {
    return null
  }

  const decide = (decision: 'approve' | 'reject') => {
    const params = decisionParams(task, decision, DEVICE)

    if (params) {
      action.run(() => codingApi.decide(params))
    }
  }

  return (
    <Section title="Approval required">
      <p className="text-xs">
        Approving runs exactly this proposal in a new isolated worktree. Your project checkout is not modified.
      </p>
      <FactList rows={approvalFacts(task)} />
      <div className="flex items-center gap-2">
        <Button disabled={action.pending || !task.actions.approve} onClick={() => decide('approve')} size="xs">
          Approve {shortFingerprint(approval.fingerprint)}
        </Button>
        <Button
          disabled={action.pending || !task.actions.reject_proposal}
          onClick={() => decide('reject')}
          size="xs"
          variant="outline"
        >
          Reject
        </Button>
        <Button onClick={() => setDetails(!details)} size="xs" variant="ghost">
          {details ? 'Hide details' : 'View details'}
        </Button>
      </div>
      {action.error && <InlineError description={action.error} title="Decision refused" />}
      {details && (
        <FactList
          rows={[
            { label: 'Approval id', value: approval.approval_id },
            { label: 'Fingerprint', value: approval.fingerprint },
            { label: 'Changes', value: approval.changes.join('; ') },
            { label: 'Pre-review', value: approval.review_rationale },
            {
              label: 'Models',
              value: Object.entries(task.models)
                .map(([k, v]) => `${k}=${v}`)
                .join(', ')
            },
            ...routingFacts(task)
          ]}
        />
      )}
      <DiffView label="Proposed diff" text={approval.proposed_diff} truncated={approval.proposed_diff_truncated} />
    </Section>
  )
}

function ExecutionSection({ task }: { task: CodingTask }) {
  const action = useTaskAction(task.task_id)
  const execution = task.execution

  if (!execution) {
    return null
  }

  const reviewer = execution.reviewer

  return (
    <Section title={`Result — attempt ${execution.attempt + 1}`}>
      <FactList
        rows={[
          { label: 'Changed files', value: execution.files_changed.join(', ') || 'none' },
          { label: 'Lines', value: `+${execution.additions} −${execution.deletions}` },
          { label: 'Reviewer', value: `${reviewer.verdict.toUpperCase()} — ${reviewer.rationale}` },
          { label: 'Commit status', value: execution.commit_status },
          { label: 'Worktree', value: `${execution.worktree.path} (${execution.worktree.branch})` },
          ...(execution.impact
            ? [
                {
                  label: 'Impact',
                  value: `risk ${execution.impact.risk}; ${execution.impact.reasons.join('; ') || 'no notes'}`
                }
              ]
            : []),
          ...execution.reasons.map(reason => ({ label: 'Blocked', value: reason }))
        ]}
      />
      <ul className="flex flex-col gap-1 text-xs">
        {execution.tests.map((test, index) => (
          <li key={`${test.check}-${index}`}>
            <Badge
              size="xs"
              variant={test.status === 'passed' ? 'success' : test.status === 'failed' ? 'destructive' : 'muted'}
            >
              {test.status}
            </Badge>{' '}
            {test.check} <span className="text-muted-foreground">({test.seconds}s)</span>
            {test.status === 'failed' && (
              <pre className="mt-1 max-h-40 overflow-auto bg-muted p-1 font-mono text-[0.65rem]">{test.output}</pre>
            )}
          </li>
        ))}
      </ul>
      {reviewer.findings
        .filter(f => f.severity !== 'pass')
        .map((finding, index) => (
          <p className="text-xs text-destructive" key={index}>
            {finding.severity.toUpperCase()}: {finding.message}
          </p>
        ))}
      <div className="flex items-center gap-2">
        {task.actions.keep && (
          <Button disabled={action.pending} onClick={() => action.run(() => codingApi.keep(task.task_id))} size="xs">
            Keep
          </Button>
        )}
        {task.actions.repair && (
          <Button
            disabled={action.pending}
            onClick={() => action.run(() => codingApi.repair(task.task_id))}
            size="xs"
            variant="outline"
          >
            Ask for a repair (needs a new approval)
          </Button>
        )}
        {task.actions.reject && (
          <Button
            disabled={action.pending}
            onClick={() => action.run(() => codingApi.reject(task.task_id))}
            size="xs"
            variant="outline"
          >
            Reject result
          </Button>
        )}
      </div>
      {action.error && <InlineError description={action.error} title="Action refused" />}
      <DiffView label="Actual diff" text={execution.actual_diff} truncated={execution.actual_diff_truncated} />
    </Section>
  )
}

const COMMITTED_STAGES = new Set(['committed', 'integration_preview', 'integrating', 'integrated'])

function ReadyToIntegrate({ result, task }: { result: CodingResult; task: CodingTask }) {
  const action = useTaskAction(task.task_id)

  return (
    <Section title="Ready to integrate">
      <FactList
        rows={[
          { label: 'Source branch', value: result.worktree_branch },
          { label: 'Target branch', value: result.target_branch },
          { label: 'Commit', value: result.result_commit.slice(0, 12) },
          { label: 'Tests', value: result.tests.map(t => `${t.check}: ${t.status}`).join('; ') || 'none recorded' },
          { label: 'Risk', value: (task.plan?.risk ?? 'unknown').toUpperCase() },
          { label: 'Reviewer', value: result.reviewer_verdict.toUpperCase() }
        ]}
      />
      <div className="flex items-center gap-2">
        <Button
          disabled={action.pending || !task.actions.integration_preview}
          onClick={() => action.run(() => codingApi.integrationPreview(task.task_id))}
          size="xs"
        >
          Preview integration
        </Button>
      </div>
      {action.error && <InlineError description={action.error} title="Preview refused" />}
    </Section>
  )
}

function IntegrationPreviewCard({ preview, task }: { preview: CodingIntegrationPreview; task: CodingTask }) {
  const action = useTaskAction(task.task_id)
  const [confirmed, setConfirmed] = useState(false)
  const canApply = Boolean(task.actions.integration_approve)
  const token = task.integration?.token ?? ''

  return (
    <Section title="Integration preview — nothing has changed yet">
      <FactList rows={integrationFacts(preview)} />
      {preview.drift_commits.length > 0 && (
        <pre className="max-h-32 overflow-auto bg-muted p-1 font-mono text-[0.65rem]">
          {preview.drift_commits.join('\n')}
        </pre>
      )}
      {canApply && (
        <label className="flex items-center gap-2 text-xs">
          <input checked={confirmed} onChange={event => setConfirmed(event.target.checked)} type="checkbox" />
          Apply this result to a new integration branch, re-run the checks and review the final diff. The target branch
          is not changed.
        </label>
      )}
      <div className="flex items-center gap-2">
        {canApply && (
          <Button
            disabled={action.pending || !confirmed}
            onClick={() => action.run(() => codingApi.integrationApprove(task.task_id, token))}
            size="xs"
          >
            Apply to integration branch
          </Button>
        )}
        <Button
          disabled={action.pending || !task.actions.integration_cancel}
          onClick={() => action.run(() => codingApi.integrationCancel(task.task_id))}
          size="xs"
          variant="outline"
        >
          Cancel
        </Button>
      </div>
      {action.error && <InlineError description={action.error} title="Integration refused" />}
    </Section>
  )
}

function IntegratedCard({ integration }: { integration: CodingIntegration }) {
  const review = integration.review

  return (
    <Section title="Integrated on an integration branch">
      <FactList
        rows={[
          { label: 'Branch', value: integration.branch ?? '' },
          { label: 'Commit', value: (integration.integration_commit ?? '').slice(0, 12) },
          { label: 'Files', value: (integration.final_files ?? []).join(', ') },
          { label: 'Checks', value: (integration.checks ?? []).map(c => `${c.check}: ${c.status}`).join('; ') },
          { label: 'Final review', value: `${(review?.verdict ?? '').toUpperCase()} — ${review?.rationale ?? ''}` },
          { label: 'Patch', value: integration.patch_changed ? 'changed by the replay — reviewed again' : 'unchanged' },
          { label: 'Note', value: 'Not merged into the target branch. Not pushed.' }
        ]}
      />
      <DiffView
        label="Final integration diff"
        text={integration.final_diff ?? ''}
        truncated={Boolean(integration.final_diff_truncated)}
      />
    </Section>
  )
}

function IntegrationSection({ task }: { task: CodingTask }) {
  const integration = task.integration
  const preview = integration?.preview

  if (task.stage === 'committed' && task.result) {
    return <ReadyToIntegrate result={task.result} task={task} />
  }

  if (task.stage === 'integration_preview' && preview) {
    return <IntegrationPreviewCard preview={preview} task={task} />
  }

  if (task.stage === 'integrated' && integration) {
    return <IntegratedCard integration={integration} />
  }

  return null
}

function PrSection({ task }: { task: CodingTask }) {
  const action = useTaskAction(task.task_id)
  const [title, setTitle] = useState<null | string>(null)
  const [body, setBody] = useState<null | string>(null)
  const pr = task.pr

  if (task.stage !== 'integrated') {
    return null
  }

  if (!pr || pr.status === 'cancelled') {
    return (
      <Section title="Pull request preview">
        <Button
          disabled={action.pending || !task.actions.pr_prepare}
          onClick={() => action.run(() => codingApi.prPrepare(task.task_id))}
          size="xs"
          variant="outline"
        >
          Prepare PR preview
        </Button>
        {action.error && <InlineError description={action.error} title="PR preview refused" />}
      </Section>
    )
  }

  const save = (status?: string) =>
    action.run(() => codingApi.prUpdate(task.task_id, { body: body ?? pr.body, status, title: title ?? pr.title }))

  return (
    <Section title={`Pull request preview — ${pr.status.replaceAll('_', ' ')}`}>
      <p className="text-xs text-muted-foreground">{pr.message}</p>
      <FactList
        rows={[
          { label: 'Source', value: pr.source_branch },
          { label: 'Target', value: pr.target_branch },
          {
            label: 'Tests',
            value: `${pr.tests.passed} passed${pr.tests.failed.length ? `; failed: ${pr.tests.failed.join(', ')}` : ''}`
          }
        ]}
      />
      <Input onChange={event => setTitle(event.target.value)} value={title ?? pr.title} />
      <Textarea
        className="min-h-32 font-mono text-xs"
        onChange={event => setBody(event.target.value)}
        value={body ?? pr.body}
      />
      <div className="flex items-center gap-2">
        <Button disabled={action.pending || !task.actions.pr_edit} onClick={() => save()} size="xs">
          Save
        </Button>
        <Button
          disabled={action.pending || !task.actions.pr_edit}
          onClick={() => save('approved_for_later')}
          size="xs"
          variant="outline"
        >
          Approve PR creation later
        </Button>
        <Button
          disabled={action.pending}
          onClick={() => action.run(() => codingApi.prUpdate(task.task_id, { status: 'cancelled' }))}
          size="xs"
          variant="ghost"
        >
          Cancel
        </Button>
      </div>
      {action.error && <InlineError description={action.error} title="PR preview refused" />}
    </Section>
  )
}

function CommitSection({ task }: { task: CodingTask }) {
  const action = useTaskAction(task.task_id)
  const [message, setMessage] = useState<null | string>(null)
  const [confirmed, setConfirmed] = useState(false)
  const commit = task.commit

  if (COMMITTED_STAGES.has(task.stage) && commit?.hash) {
    return (
      <Section title="Committed in the worktree">
        <p className="text-xs">
          Commit <span className="font-mono">{commit.hash.slice(0, 12)}</span> on branch{' '}
          <span className="font-mono">{commit.branch ?? task.result?.worktree_branch}</span>. Not pushed, not merged.
        </p>
      </Section>
    )
  }

  if (!task.actions.commit_prepare) {
    return null
  }

  if (!commit?.token) {
    return (
      <Section title="Commit">
        <Button
          disabled={action.pending}
          onClick={() => action.run(() => codingApi.commitPrepare(task.task_id))}
          size="xs"
          variant="outline"
        >
          Commit locally…
        </Button>
        {action.error && <InlineError description={action.error} title="Commit unavailable" />}
      </Section>
    )
  }

  const text = message ?? commit.suggested_message ?? ''

  return (
    <Section title="Commit locally — review before confirming">
      <FactList
        rows={[
          { label: 'Files', value: (commit.files ?? []).join(', ') },
          { label: 'Diff stat', value: commit.stat || `+${commit.additions} −${commit.deletions}` },
          { label: 'Branch', value: `${commit.branch} (worktree ${commit.worktree_path})` },
          { label: 'Parent', value: `${commit.parent_branch} — unchanged` },
          { label: 'Note', value: commit.note ?? '' }
        ]}
      />
      <Textarea
        className="min-h-24 font-mono text-xs"
        onChange={event => setMessage(event.target.value)}
        value={text}
      />
      <label className="flex items-center gap-2 text-xs">
        <input checked={confirmed} onChange={event => setConfirmed(event.target.checked)} type="checkbox" />I reviewed
        the files and message above and want to commit them locally.
      </label>
      <div className="flex items-center gap-2">
        <Button
          disabled={action.pending || !confirmed || !text.trim() || !task.actions.commit_confirm}
          onClick={() => action.run(() => codingApi.commitConfirm(task.task_id, text, commit.token ?? ''))}
          size="xs"
        >
          Commit
        </Button>
        <Button
          onClick={() => {
            setMessage(null)
            setConfirmed(false)
          }}
          size="xs"
          variant="ghost"
        >
          Reset message
        </Button>
      </div>
      {action.error && <InlineError description={action.error} title="Commit refused" />}
    </Section>
  )
}

function TaskDetail({ taskId }: { taskId: string }) {
  const { data: task, error } = useQuery({
    queryFn: () => codingApi.get(taskId),
    queryKey: TASK_KEY(taskId),
    refetchInterval: query => ((query.state.data as CodingTask | undefined)?.busy ? 1_500 : false)
  })

  const client = useQueryClient()
  const stage = task?.stage
  const missing = Boolean(error) && /No such coding task/.test(errorText(error))

  // A stage change refreshes the task list so its badges never lag behind the detail view.
  useEffect(() => {
    if (stage) {
      void client.invalidateQueries({ queryKey: LIST_KEY })
    }
  }, [client, stage])

  useEffect(() => {
    if (missing) {
      $selectedCodingTask.set(null)
    }
  }, [missing])

  if (error) {
    return <InlineError description={errorText(error)} title="Task unavailable" />
  }

  if (!task) {
    return <p className="text-xs text-muted-foreground">Loading…</p>
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Badge variant={BADGE[stageTone(task.stage)]}>{task.stage_label}</Badge>
        <span className="truncate text-sm">{task.description}</span>
      </div>
      <Pipeline task={task} />
      {task.error && <InlineError description={task.error} title={task.stage === 'blocked' ? 'Blocked' : 'Problem'} />}
      {task.plan && (
        <Section title="Plan">
          <FactList
            rows={[
              { label: 'Summary', value: task.plan.summary },
              { label: 'Files', value: [...task.plan.files_to_change, ...task.plan.new_files].join(', ') },
              { label: 'Risk', value: task.plan.risk.toUpperCase() },
              { label: 'Steps', value: task.plan.steps.join('; ') }
            ]}
          />
        </Section>
      )}
      <ApprovalCard task={task} />
      <ExecutionSection task={task} />
      <CommitSection task={task} />
      <IntegrationSection task={task} />
      <PrSection task={task} />
      <RemoteSection task={task} />
      {task.cleanup.worktrees?.length ? (
        <Section title="Cleanup">
          {task.cleanup.worktrees.map((entry, index) => (
            <p className="text-xs" key={index}>
              {entry.pruned
                ? `Removed ${String(entry.path)}${entry.archive ? ` (archived to ${String(entry.archive)})` : ''}.`
                : `Worktree cleanup could not be proven safe — preserved for inspection: ${String(entry.path)}. ${String(entry.note ?? '')}`}
            </p>
          ))}
        </Section>
      ) : null}
    </div>
  )
}

function NewTask() {
  const cwd = useValue(host.state.cwd)
  const client = useQueryClient()
  const [description, setDescription] = useState('')
  const [files, setFiles] = useState('')
  const [error, setError] = useState('')

  const start = useMutation({
    mutationFn: () =>
      codingApi.start(
        description,
        cwd,
        files
          .split(',')
          .map(f => f.trim())
          .filter(Boolean)
      ),
    onError: (err: unknown) => setError(errorText(err)),
    onSuccess: (task: CodingTask) => {
      setError('')
      setDescription('')
      client.setQueryData(TASK_KEY(task.task_id), task)
      void client.invalidateQueries({ queryKey: LIST_KEY })
      $selectedCodingTask.set(task.task_id)
    }
  })

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-muted-foreground">Project: {cwd || 'no workspace selected'}</p>
      <Textarea
        className="min-h-20 text-xs"
        onChange={event => setDescription(event.target.value)}
        placeholder="Describe the change, e.g. “Add multiply(a, b) to calc/ops.py and a test”"
        value={description}
      />
      <Input
        onChange={event => setFiles(event.target.value)}
        placeholder="Files (optional, comma separated)"
        value={files}
      />
      <Button disabled={!cwd || !description.trim() || start.isPending} onClick={() => start.mutate()} size="xs">
        Plan the change
      </Button>
      {error && <InlineError description={error} title="Could not start" />}
    </div>
  )
}

export function CodingPage() {
  const selected = useValue($selectedCodingTask)
  const { data: tasks = [] } = useQuery({ queryFn: codingApi.list, queryKey: LIST_KEY, refetchInterval: 10_000 })

  return (
    <div className="grid h-full grid-cols-[18rem_1fr] gap-4 overflow-hidden p-4">
      <aside className="flex flex-col gap-4 overflow-auto">
        <h2 className="text-sm font-semibold">Coding</h2>
        <NewTask />
        <ul className="flex flex-col gap-1">
          {tasks.map(row => (
            <li key={row.task_id}>
              <button
                className={cn(
                  'w-full rounded-[3px] px-2 py-1 text-left text-xs hover:bg-muted',
                  selected === row.task_id && 'bg-muted'
                )}
                onClick={() => $selectedCodingTask.set(row.task_id)}
                type="button"
              >
                <Badge size="xs" variant={BADGE[stageTone(row.stage)]}>
                  {row.stage.replaceAll('_', ' ')}
                </Badge>{' '}
                <span className="line-clamp-2">{row.description}</span>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <main className="overflow-auto">
        {selected ? (
          <TaskDetail taskId={selected} />
        ) : (
          <p className="text-xs text-muted-foreground">Start or select a coding task.</p>
        )}
      </main>
    </div>
  )
}
