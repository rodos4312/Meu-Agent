import { useStore } from '@nanostores/react'

import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import type { SessionInfo } from '@/hermes'
import { useI18n } from '@/i18n'
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
  const { states, verifiedCount } = t.projectProgress

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

        const verified = plan.tasks.filter(task => task.state === 'verified').length

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
            <ul className="space-y-2">
              {plan.tasks.map(task => (
                <li className="break-words" key={task.id}>
                  <div>{task.goal}</div>
                  <div className="text-(--ui-text-secondary)">
                    {Object.hasOwn(states, task.state) ? states[task.state as keyof typeof states] : task.state}
                    {task.model && ` · ${task.model}`}
                  </div>
                  {task.artifacts.map(file =>
                    canReveal ? (
                      <button
                        className="block max-w-full truncate text-left underline"
                        key={file.path}
                        onClick={() => void revealPath(file.path)}
                        title={file.path}
                        type="button"
                      >
                        {file.name}
                      </button>
                    ) : (
                      <div key={file.path}>{file.name}</div>
                    )
                  )}
                </li>
              ))}
            </ul>
          </details>
        )
      })}
    </section>
  )
}
