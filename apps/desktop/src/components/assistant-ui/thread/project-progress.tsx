import { useAuiState } from '@assistant-ui/react'
import { useStore } from '@nanostores/react'
import { useMemo } from 'react'

import { useSessionView } from '@/app/chat/session-view'
import { parseMaybeObject, toolCallFailed } from '@/components/assistant-ui/tool/fallback-model'
import { CoordinatorTaskDetails } from '@/components/chat/coordinator-task-details'
import { PreviewAttachment } from '@/components/chat/preview-attachment'
import { Progress } from '@/components/ui/progress'
import { useI18n } from '@/i18n'
import { coordinatorCall, coordinatorLiveModel, coordinatorTasks } from '@/lib/coordinator-progress'
import { useSessionSlice } from '@/lib/use-session-slice'
import { $subagentsBySession } from '@/store/subagents'

export function ProjectProgress({ result, toolCallId }: { result: unknown; toolCallId: string }) {
  const { t } = useI18n()
  const labels = t.projectProgress
  const sessionId = useStore(useSessionView().$runtimeId)
  const live = useSessionSlice($subagentsBySession, sessionId)
  const parts = useAuiState(s => s.message.content)
  const messageRunning = useAuiState(s => s.message.status?.type === 'running')
  const project = parseMaybeObject(result).project

  const { firstId, snapshot, pendingRun } = useMemo(() => {
    let firstId: string | undefined
    let snapshot: Record<string, unknown> = {}
    let pendingRun = false

    // Keep one card in place as this reply receives later snapshots of the same project.
    for (const part of parts) {
      if (part.type !== 'tool-call') {
        continue
      }

      const args = coordinatorCall(part.toolName, part.args)

      if (!args) {continue}

      if (part.result === undefined) {
        if (args.project === project && args.action === 'run' && !('completedAt' in part && part.completedAt)) {
          pendingRun = true
        }

        continue
      }

      const update = parseMaybeObject(part.result)

      if (update.project === project && !toolCallFailed(part)) {
        firstId ??= part.toolCallId
        snapshot = update
      }
    }

    return { firstId, snapshot, pendingRun }
  }, [parts, project])

  const tasks = useMemo(() => coordinatorTasks(snapshot), [snapshot])

  if (typeof project !== 'string' || firstId !== toolCallId) {
    return null
  }

  const { project_folder_url: folder, root } = snapshot

  const folderLink = typeof folder === 'string' && /^file:\/\/\/(?!\/)/i.test(folder) && (
    <PreviewAttachment target={folder} />
  )

  const path = typeof root === 'string' && <div className="text-muted-foreground break-all text-xs">{root}</div>

  const verified = tasks.filter(task => task.state === 'verified').length

  return (
    <div className="my-1 min-w-0 max-w-[640px]" data-slot="project-progress">
      {tasks.length > 0 ? (
        <details className="border-border/70 bg-muted/20 rounded-lg border px-3 py-2 text-sm">
          <summary className="focus-visible:ring-ring cursor-pointer rounded-sm focus-visible:ring-2">
            <span className="break-words font-medium">{project}</span>
            <span className="text-muted-foreground ms-2 text-xs">{labels.verifiedCount(verified, tasks.length)}</span>
            {messageRunning && pendingRun && (
              <span className="text-muted-foreground ms-2 text-xs" role="status">
                {labels.runningBatch}
              </span>
            )}
          </summary>
          <div className="mt-2 space-y-1">
            <p className="text-xs text-muted-foreground">{labels.snapshot}</p>
            <Progress aria-label={labels.verifiedCount(verified, tasks.length)} value={verified / tasks.length} />
          </div>
          <ul className="mt-2 space-y-3">
            {tasks.map(task => (
              <li key={task.id}>
                <CoordinatorTaskDetails
                  liveModel={coordinatorLiveModel(task, snapshot, live)}
                  renderArtifact={file => <PreviewAttachment target={file.path} />}
                  task={task}
                />
              </li>
            ))}
          </ul>
          {path}
        </details>
      ) : (
        path
      )}
      {folderLink}
    </div>
  )
}
