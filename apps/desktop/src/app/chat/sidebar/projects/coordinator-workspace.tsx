import { useStore } from '@nanostores/react'

import { CoordinatorTaskDetails } from '@/components/chat/coordinator-task-details'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { Progress } from '@/components/ui/progress'
import type { SessionInfo } from '@/hermes'
import { useI18n } from '@/i18n'
import { coordinatorTasks } from '@/lib/coordinator-progress'
import { $activeConnectionId } from '@/store/connections'
import { shouldOfferLocalReveal } from '@/store/file-actions'
import { revealPath } from '@/store/projects'

import type { SidebarProjectTree } from './workspace-groups'

export function CoordinatorWorkspace({
  project,
  onRefresh,
  onResumeSession
}: {
  project: SidebarProjectTree
  onRefresh?: () => void
  onResumeSession?: (sessionId: string, session: SessionInfo) => void
}) {
  const { t } = useI18n()
  const connectionId = useStore($activeConnectionId)
  const plans = project.coordinatorPlans

  if (!plans?.length) {
    return null
  }

  const canReveal = shouldOfferLocalReveal(connectionId)
  const sessions = project.repos.flatMap(repo => repo.groups.flatMap(group => group.sessions))
  const { verifiedCount } = t.projectProgress

  return (
    <section aria-label="Meu Coordinator" className="mx-2 mb-2 rounded-md border p-2 text-xs">
      <div className="flex items-center justify-between font-medium">
        <span>Meu Coordinator</span>
        {onRefresh && (
          <Button aria-label={t.common.refresh} onClick={onRefresh} size="icon-xs" variant="ghost">
            <Codicon name="refresh" />
          </Button>
        )}
      </div>
      {plans.map(plan => {
        const id = plan.session_id

        const session = id
          ? sessions.find(row => row.id === id || row._lineage_root_id === id || row._lineage_ids?.includes(id))
          : undefined

        const tasks = coordinatorTasks({ progress: plan.tasks })
        const verified = tasks.filter(task => task.state === 'verified').length

        return (
          <details className="mt-1" key={plan.id}>
            <summary className="cursor-pointer break-words">
              {plan.id} · {verifiedCount(verified, plan.tasks.length)}
            </summary>
            <div className="my-1 flex flex-wrap gap-1">
              {session && onResumeSession && (
                <Button onClick={() => onResumeSession(session.id, session)} size="xs" variant="ghost">
                  {t.common.continue}
                </Button>
              )}
              {canReveal && (
                <Button onClick={() => void revealPath(plan.root)} size="xs" variant="ghost">
                  {t.sidebar.projects.reveal}
                </Button>
              )}
            </div>
            {!!tasks.length && (
              <Progress aria-label={verifiedCount(verified, tasks.length)} value={verified / tasks.length} />
            )}
            <p className="text-(--ui-text-secondary)">{t.projectProgress.snapshot}</p>
            <ul className="space-y-3">
              {tasks.map(task => (
                <li key={task.id}>
                  <CoordinatorTaskDetails
                    renderArtifact={file =>
                      canReveal ? (
                        <Button
                          className="max-w-full truncate"
                          key={file.path}
                          onClick={() => void revealPath(file.path)}
                          size="inline"
                          variant="link"
                        >
                          {file.name}
                        </Button>
                      ) : (
                        <span>{file.name}</span>
                      )
                    }
                    task={task}
                  />
                </li>
              ))}
            </ul>
          </details>
        )
      })}
    </section>
  )
}
