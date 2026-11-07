import { useStore } from '@nanostores/react'

import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { Tip } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n'
import { displayPath } from '@/lib/display-path'
import { $activeConnectionId } from '@/store/connections'
import { shouldOfferLocalReveal } from '@/store/file-actions'
import { copyPath, projectRootCwd, revealPath } from '@/store/projects'

import type { SidebarProjectTree } from './workspace-groups'

/** The backend's folder, with actions scoped to the selected execution device. */
export function ProjectLocation({ project }: { project: SidebarProjectTree }) {
  const { t } = useI18n()
  const connection = useStore($activeConnectionId)
  const path = projectRootCwd(project)
  const p = t.sidebar.projects

  if (project.isNoProject || !path) {
    return null
  }

  return (
    <div className="mx-2 mb-2 flex min-w-0 items-center gap-1 rounded-md border px-2 py-1">
      <Codicon className="shrink-0 text-(--ui-text-tertiary)" name="folder" size={14} />
      <span className="min-w-0 flex-1 truncate text-xs text-(--ui-text-secondary)" title={path}>
        {displayPath(path)}
      </span>
      <Tip label={p.copyPath}>
        <Button aria-label={p.copyPath} onClick={() => void copyPath(path)} size="icon-xs" variant="ghost">
          <Codicon name="copy" size={14} />
        </Button>
      </Tip>
      {shouldOfferLocalReveal(connection) && (
        <Tip label={p.reveal}>
          <Button aria-label={p.reveal} onClick={() => void revealPath(path)} size="icon-xs" variant="ghost">
            <Codicon name="folder-opened" size={14} />
          </Button>
        </Tip>
      )}
    </div>
  )
}
