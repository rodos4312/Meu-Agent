import { useStore } from '@nanostores/react'

import { $apiRequestScope } from '@/api/client'
import { PersonalDevicesSettings } from './personal-devices-settings'

export function MobilePreviewPanel() {
  const { profile } = useStore($apiRequestScope)
  return <PersonalDevicesSettings profile={profile ?? undefined} />
}
