import type * as React from 'react'

import { Codicon } from '@/components/ui/codicon'
import { Tip } from '@/components/ui/tooltip'
import type { SessionInfo } from '@/hermes'

import { phoneOriginDevice, phoneOriginLabel } from './phone-origin'

/** The row's trailing-slot entry for a chat created on a phone, or none. */
export function phoneOriginTrailing(session: SessionInfo): { key: string; node: React.ReactNode }[] {
  const device = phoneOriginDevice(session)

  if (device === null) {
    return []
  }

  const label = phoneOriginLabel(device)

  return [
    {
      key: 'phone',
      node: (
        <Tip label={label}>
          <Codicon
            aria-hidden={false}
            aria-label={label}
            className="text-(--ui-text-tertiary)"
            name="device-mobile"
            role="img"
            size="0.75rem"
          />
        </Tip>
      )
    }
  ]
}
