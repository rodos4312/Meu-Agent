import type { ReactNode } from 'react'

import { Sidebar } from '@/components/ui/sidebar'
import { cn } from '@/lib/utils'

import type { AppView } from '../../routes'
import { MeuCapabilitySidebar } from '../../shell/meu-navigation'

interface ChatSidebarFrameProps {
  children: ReactNode
  currentView: AppView
  panesFlipped: boolean
}

export function ChatSidebarFrame({ children, currentView, panesFlipped }: ChatSidebarFrameProps) {
  return (
    <Sidebar
      className={cn(
        // The tree owns visibility, including narrow overlay placement.
        'relative h-full min-w-0 overflow-hidden border-t-0 border-b-0 text-foreground transition-none',
        panesFlipped ? 'border-l border-r-0' : 'border-r border-l-0',
        'border-(--sidebar-edge-border) bg-(--ui-sidebar-surface-background) opacity-100'
      )}
      collapsible="none"
      data-meu-sidebar-mode={currentView}
      data-tip-region=""
      data-tour="sessions-sidebar"
    >
      {children}
      {currentView === 'capabilities' && <MeuCapabilitySidebar />}
    </Sidebar>
  )
}
