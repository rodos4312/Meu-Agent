import { useStore } from '@nanostores/react'
import { useMemo } from 'react'

import type { SessionInfo } from '@/hermes'
import { $sidebarPhoneOnly } from '@/store/layout'

import { phoneOriginDevice } from './phone-origin'
import { filterSessionsByProfileScope } from './profile-scope'

/** A session list narrowed to the active profile scope. */
export function useProfileScoped(list: SessionInfo[], profileScope: Parameters<typeof filterSessionsByProfileScope>[1]) {
  return useMemo(() => filterSessionsByProfileScope(list, profileScope), [list, profileScope])
}

/** The sidebar's session pool after profile scope and the phone-only filter. */
export function useScopedSessions(
  sessions: SessionInfo[],
  archivedSessions: SessionInfo[],
  showArchived: boolean,
  profileScope: Parameters<typeof filterSessionsByProfileScope>[1]
): SessionInfo[] {
  const phoneOnly = useStore($sidebarPhoneOnly)

  return useMemo(() => {
    const scoped = filterSessionsByProfileScope(showArchived ? archivedSessions : sessions, profileScope)

    return phoneOnly ? scoped.filter(session => phoneOriginDevice(session) !== null) : scoped
  }, [sessions, archivedSessions, showArchived, profileScope, phoneOnly])
}
