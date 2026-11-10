import { useStore } from '@nanostores/react'

import { $apiRequestScope } from '@/api/client'
import { PersonalDevicesSettings } from './personal-devices-settings'
import { ProjectSyncSettings } from './project-sync-settings'

export function MobilePreviewPanel() {
  const { profile } = useStore($apiRequestScope)
  return <><PersonalDevicesSettings profile={profile ?? undefined} /><ProjectSyncSettings profile={profile ?? undefined} /></>
}
