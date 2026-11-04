import { useAuiState } from '@assistant-ui/react'
import { useMemo } from 'react'

import { parseMaybeObject, toolCallFailed } from '@/components/assistant-ui/tool/fallback-model'
import { PreviewAttachment } from '@/components/chat/preview-attachment'
import { useI18n } from '@/i18n'
import { helperModelLabel } from '@/lib/model-status-label'

export function ProjectProgress({ result, toolCallId }: { result: unknown; toolCallId: string }) {
  const { t } = useI18n()
  const labels = t.projectProgress
  const parts = useAuiState(s => s.message.content)
  const messageRunning = useAuiState(s => s.message.status?.type === 'running')
  const project = parseMaybeObject(result).project

  const { firstId, snapshot, pendingRun } = useMemo(() => {
    let firstId: string | undefined
    let snapshot: Record<string, unknown> = {}
    let pendingRun = false

    // Keep one card in place as this reply receives later snapshots of the same project.
    for (const part of parts) {
      if (part.type !== 'tool-call' || part.toolName !== 'coordinate_project') {
        continue
      }

      if (part.result === undefined) {
        if (
          part.args.project === project &&
          part.args.action === 'run' &&
          !('completedAt' in part && part.completedAt)
        ) {
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

  if (typeof project !== 'string' || firstId !== toolCallId) {
    return null
  }

  const { project_folder_url: folder, root } = snapshot

  const folderLink = typeof folder === 'string' && /^file:\/\/\/(?!\/)/i.test(folder) && (
    <PreviewAttachment target={folder} />
  )

  const path = typeof root === 'string' && <div className="text-muted-foreground break-all text-xs">{root}</div>

  const tasks = Object.entries(parseMaybeObject(snapshot.tasks)).map(
    ([id, row]) => [id, parseMaybeObject(row)] as const
  )

  const verified = tasks.filter(([, row]) => row.state === 'verified').length

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
          <ul className="divide-border/70 mt-2 divide-y">
            {tasks.map(([id, row]) => {
              const task = parseMaybeObject(row.task)
              const repair = parseMaybeObject(row.repair)
              const receipt = parseMaybeObject(row.result)
              const route = parseMaybeObject(receipt.route)
              const helper = helperModelLabel(route.provider, route.model ?? receipt.model)
              const { state, attempt } = row

              const label =
                typeof state === 'string' && Object.hasOwn(labels.states, state)
                  ? labels.states[state as keyof typeof labels.states]
                  : null

              return (
                <li className="space-y-1 py-2 text-xs" key={id}>
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="break-all font-medium">{id}</span>
                    {label && <span className="text-muted-foreground">{label}</span>}
                    {typeof attempt === 'number' && attempt > 0 && (
                      <span className="text-muted-foreground">{labels.attempt(attempt)}</span>
                    )}
                    {helper &&
                      state !== 'pending' &&
                      state !== 'running' &&
                      state !== 'interrupted' && <span className="text-muted-foreground break-all">{helper}</span>}
                  </div>
                  {typeof task.goal === 'string' && <p className="break-words">{task.goal}</p>}
                  {typeof task.acceptance === 'string' && (
                    <div className="text-muted-foreground break-words">
                      <span className="font-medium">{labels.acceptance}</span>
                      <p>{task.acceptance}</p>
                    </div>
                  )}
                  {typeof repair.check === 'string' && (
                    <div className="text-muted-foreground break-words">
                      <span className="font-medium">{labels.repair}</span>
                      <p>{repair.check}</p>
                    </div>
                  )}
                </li>
              )
            })}
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
