import type { ReactNode } from 'react'

import { useI18n } from '@/i18n'
import type { CoordinatorTaskView } from '@/lib/coordinator-progress'
import { helperModelLabel } from '@/lib/model-status-label'

export function CoordinatorTaskDetails({
  task,
  liveModel,
  renderArtifact
}: {
  task: CoordinatorTaskView
  liveModel?: string
  renderArtifact?: (file: CoordinatorTaskView['artifacts'][number]) => ReactNode
}) {
  const { t } = useI18n()
  const labels = t.projectProgress

  const state = Object.hasOwn(labels.states, task.state)
    ? labels.states[task.state as keyof typeof labels.states]
    : labels.unknown

  const helper = helperModelLabel(task.provider, liveModel || task.model)
  const review = task.review

  return (
    <div className="min-w-0 space-y-1 break-words text-xs">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="break-all font-medium">{task.id}</span>
        <span className={task.state === 'failed' ? 'text-destructive' : 'text-muted-foreground'}>{state}</span>
        {typeof task.attempt === 'number' && task.attempt > 0 && (
          <span className="text-muted-foreground">{labels.attempt(task.attempt)}</span>
        )}
        {helper && <span className="break-all text-muted-foreground">{helper}</span>}
      </div>
      <p>{task.goal}</p>
      {task.review_of && (
        <p className="text-muted-foreground">
          {labels.reviewOf} · {task.review_of}
        </p>
      )}
      {!!task.depends_on?.length && (
        <p className="text-muted-foreground">
          {labels.dependencies} · {task.depends_on.join(', ')}
        </p>
      )}
      {task.acceptance && (
        <div className="text-muted-foreground">
          <span className="font-medium">{labels.acceptance}</span>
          <p className="whitespace-pre-wrap">{task.acceptance}</p>
        </div>
      )}
      {task.repair_check && (
        <div className="text-muted-foreground">
          <span className="font-medium">{labels.repair}</span>
          <p>{task.repair_check}</p>
        </div>
      )}
      {review && (
        <div className="space-y-1 text-muted-foreground">
          <p className="font-medium">
            {labels.reviewResult} · {labels.verdicts[review.verdict as keyof typeof labels.verdicts]}
          </p>
          <p className="whitespace-pre-wrap">{review.check}</p>
          <p className="whitespace-pre-wrap">{review.observed}</p>
        </div>
      )}
      {task.evidence && (
        <details className="text-muted-foreground">
          <summary className="cursor-pointer">{labels.evidence}</summary>
          <p className="whitespace-pre-wrap">{task.evidence}</p>
        </details>
      )}
      {task.error && <p className="whitespace-pre-wrap text-destructive">{task.error}</p>}
      {!!task.artifacts.length && (
        <div className="space-y-1">
          <p className="font-medium">{labels.deliverables}</p>
          {task.artifacts.map(file => (
            <div key={file.path}>{renderArtifact ? renderArtifact(file) : file.name}</div>
          ))}
        </div>
      )}
    </div>
  )
}
