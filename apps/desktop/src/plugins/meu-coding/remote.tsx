/**
 * REMOTE section of a coding task: push → pull request → merge, each with its own read-only
 * preview and its own explicit, single-use approval naming that preview's fingerprint. The
 * backend re-verifies every ref before it acts; nothing here runs on its own, force-pushes or
 * deletes a branch. Review feedback becomes a NEW task, never an automatic edit.
 */

import { Button, Input, Textarea, useQuery } from '@hermes/plugin-sdk'
import { type ReactNode, useState } from 'react'

import { codingApi } from './api'
import { type CodingTask, errorText } from './model'
import { FactList, InlineError, Section, useTaskAction } from './parts'
import {
  type CodingRemote,
  MERGE_STATUS_TEXT,
  mergeFacts,
  type MergePreview,
  prFacts,
  type PrPreview,
  prStatusFacts,
  pushFacts,
  type PushPreview,
  type RemoteKind
} from './remote-model'

type Action = ReturnType<typeof useTaskAction>

function ApproveBar({
  action,
  children,
  kind,
  label,
  task,
  fingerprint,
  enabled
}: {
  action: Action
  children: ReactNode
  enabled: boolean
  fingerprint: string
  kind: RemoteKind
  label: string
  task: CodingTask
}) {
  const [confirmed, setConfirmed] = useState(false)

  return (
    <>
      {enabled && (
        <label className="flex items-center gap-2 text-xs">
          <input checked={confirmed} onChange={event => setConfirmed(event.target.checked)} type="checkbox" />
          {children}
        </label>
      )}
      <div className="flex items-center gap-2">
        {enabled && (
          <Button
            disabled={action.pending || !confirmed}
            onClick={() => action.run(() => codingApi.remoteApprove(task.task_id, kind, fingerprint))}
            size="xs"
          >
            {label}
          </Button>
        )}
        <Button
          disabled={action.pending}
          onClick={() => action.run(() => codingApi.remoteCancel(task.task_id, kind))}
          size="xs"
          variant="ghost"
        >
          Cancel
        </Button>
      </div>
    </>
  )
}

function PushCard({ action, preview, task }: { action: Action; preview: PushPreview; task: CodingTask }) {
  return (
    <>
      <FactList rows={pushFacts(preview)} />
      {preview.status === 'blocked' && <InlineError description={preview.reason} title="Push blocked" />}
      <ApproveBar
        action={action}
        enabled={Boolean(task.actions.push_approve)}
        fingerprint={preview.fingerprint}
        kind="push"
        label="Approve push"
        task={task}
      >
        Push exactly {preview.refspec} to {preview.remote}. No force. The target branch is not touched.
      </ApproveBar>
    </>
  )
}

function PrCard({ action, preview, task }: { action: Action; preview: PrPreview; task: CodingTask }) {
  return (
    <>
      <FactList rows={prFacts(preview)} />
      <p className="text-xs font-semibold">{preview.title}</p>
      <pre className="max-h-48 overflow-auto bg-muted p-1 font-mono text-[0.65rem] whitespace-pre-wrap">
        {preview.body}
      </pre>
      <ApproveBar
        action={action}
        enabled={Boolean(task.actions.pr_create_approve)}
        fingerprint={preview.fingerprint}
        kind="pr"
        label="Create pull request"
        task={task}
      >
        Create this pull request on {preview.repository}. It does not merge anything.
      </ApproveBar>
    </>
  )
}

function MergeCard({ action, preview, task }: { action: Action; preview: MergePreview; task: CodingTask }) {
  return (
    <>
      <FactList rows={mergeFacts(preview)} />
      {preview.reasons.length > 0 && (
        <InlineError description={preview.reasons.join(' ')} title={MERGE_STATUS_TEXT[preview.status]} />
      )}
      <ApproveBar
        action={action}
        enabled={Boolean(task.actions.merge_approve)}
        fingerprint={preview.fingerprint}
        kind="merge"
        label="Approve merge"
        task={task}
      >
        Merge PR #{preview.pr_number} ({preview.method}) into {preview.target_branch} at head{' '}
        {preview.source_sha.slice(0, 12)}. This is a separate approval from the push and the PR. No branch is deleted.
      </ApproveBar>
    </>
  )
}

function PrDraft({ action, task }: { action: Action; task: CodingTask }) {
  const [title, setTitle] = useState<null | string>(null)
  const [body, setBody] = useState<null | string>(null)

  return (
    <>
      <Input
        onChange={event => setTitle(event.target.value)}
        placeholder="Title"
        value={title ?? task.pr?.title ?? ''}
      />
      <Textarea
        className="min-h-24 font-mono text-xs"
        onChange={event => setBody(event.target.value)}
        value={body ?? task.pr?.body ?? ''}
      />
      <Button
        disabled={action.pending || !task.actions.create_remote_pr}
        onClick={() =>
          action.run(() =>
            codingApi.remotePreview(task.task_id, 'pr', {
              body: body ?? task.pr?.body,
              title: title ?? task.pr?.title
            })
          )
        }
        size="xs"
        variant="outline"
      >
        Preview PR
      </Button>
    </>
  )
}

function Feedback({ task }: { task: CodingTask }) {
  const action = useTaskAction(task.task_id)
  const [open, setOpen] = useState(false)
  const [chosen, setChosen] = useState<number[]>([])

  const comments = useQuery({
    enabled: open,
    queryFn: () => codingApi.remoteFeedback(task.task_id),
    queryKey: ['meu-coding', 'feedback', task.task_id]
  })

  if (!task.actions.repair_from_feedback) {
    return null
  }

  if (!open) {
    return (
      <Button onClick={() => setOpen(true)} size="xs" variant="ghost">
        Review feedback…
      </Button>
    )
  }

  const toggle = (id: number) => setChosen(ids => (ids.includes(id) ? ids.filter(i => i !== id) : [...ids, id]))

  return (
    <div className="flex flex-col gap-1">
      {comments.error && <InlineError description={errorText(comments.error)} title="Feedback unavailable" />}
      {(comments.data ?? []).map(comment => (
        <label className="flex items-start gap-2 text-xs" key={comment.id}>
          <input checked={chosen.includes(comment.id)} onChange={() => toggle(comment.id)} type="checkbox" />
          <span>
            <span className="font-mono">
              {comment.path}:{comment.line ?? '?'}
            </span>{' '}
            ({comment.author}) {comment.body}
          </span>
        </label>
      ))}
      {comments.data?.length === 0 && <p className="text-xs text-muted-foreground">No review comments.</p>}
      <Button
        disabled={action.pending || chosen.length === 0}
        onClick={() => action.run(() => codingApi.remoteRepair(task.task_id, chosen))}
        size="xs"
        variant="outline"
      >
        Create repair task from PR feedback
      </Button>
      <p className="text-xs text-muted-foreground">
        Starts a new coding task; it is planned, reviewed and needs its own approval. Nothing is edited automatically.
      </p>
      {action.error && <InlineError description={action.error} title="Repair task refused" />}
    </div>
  )
}

function Pending({ action, remote, task }: { action: Action; remote: CodingRemote; task: CodingTask }) {
  if (remote.pending.includes('push') && remote.push_preview) {
    return <PushCard action={action} preview={remote.push_preview} task={task} />
  }

  if (remote.pending.includes('pr') && remote.pr_preview) {
    return <PrCard action={action} preview={remote.pr_preview} task={task} />
  }

  if (remote.pending.includes('merge') && remote.merge_preview) {
    return <MergeCard action={action} preview={remote.merge_preview} task={task} />
  }

  return null
}

function Done({ remote }: { remote: CodingRemote }) {
  return (
    <>
      {remote.pushed && (
        <p className="text-xs">
          Pushed <span className="font-mono">{remote.pushed.destination_branch}</span> @{' '}
          <span className="font-mono">{remote.pushed.remote_sha.slice(0, 12)}</span> to {remote.pushed.remote}.
        </p>
      )}
      {remote.pr && (
        <p className="text-xs">
          Pull request #{remote.pr.number}{' '}
          <a className="underline" href={remote.pr.url} rel="noreferrer" target="_blank">
            {remote.pr.url}
          </a>
        </p>
      )}
      {remote.pr_status && <FactList rows={prStatusFacts(remote.pr_status)} />}
      {remote.merged && (
        <p className="text-xs">
          Merged ({remote.merged.method}) as{' '}
          <span className="font-mono">{remote.merged.merge_commit_sha.slice(0, 12)}</span>
          {remote.merged.target_verified ? ' — target branch verified.' : ' — target branch NOT verified, inspect it.'}
        </p>
      )}
    </>
  )
}

export function RemoteSection({ task }: { task: CodingTask }) {
  const action = useTaskAction(task.task_id)
  const remote = task.remote
  const a = task.actions

  if (!remote) {
    return null
  }

  const idle = remote.pending.length === 0

  return (
    <Section title={`Remote — ${remote.state_label}`}>
      {remote.info && !remote.info.available && <p className="text-xs text-muted-foreground">{remote.info.reason}</p>}
      {remote.info?.available && (
        <p className="text-xs text-muted-foreground">
          {remote.info.identity} via {remote.info.name}. Nothing is sent without your approval.
        </p>
      )}
      <Done remote={remote} />
      {remote.blocked && <InlineError description={remote.blocked.reason} title="Blocked" />}
      <Pending action={action} remote={remote} task={task} />
      {idle && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            disabled={action.pending || !a.remote_detect}
            onClick={() => action.run(() => codingApi.remoteDetect(task.task_id))}
            size="xs"
            variant="ghost"
          >
            Check remote
          </Button>
          {a.push && (
            <Button
              disabled={action.pending}
              onClick={() => action.run(() => codingApi.remotePreview(task.task_id, 'push'))}
              size="xs"
            >
              Preview push
            </Button>
          )}
          {a.pr_refresh && (
            <Button
              disabled={action.pending}
              onClick={() => action.run(() => codingApi.remoteRefresh(task.task_id))}
              size="xs"
              variant="outline"
            >
              Refresh PR
            </Button>
          )}
          {a.merge && (
            <Button
              disabled={action.pending}
              onClick={() => action.run(() => codingApi.remotePreview(task.task_id, 'merge', { method: 'squash' }))}
              size="xs"
              variant="outline"
            >
              Preview merge
            </Button>
          )}
        </div>
      )}
      {idle && a.create_remote_pr && <PrDraft action={action} task={task} />}
      <Feedback task={task} />
      {action.error && <InlineError description={action.error} title="Remote action refused" />}
    </Section>
  )
}
