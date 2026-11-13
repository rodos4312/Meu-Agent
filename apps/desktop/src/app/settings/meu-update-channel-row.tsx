import { useStore } from '@nanostores/react'
import { type ReactElement, useState } from 'react'

import { Button } from '@/components/ui/button'
import { SegmentedControl } from '@/components/ui/segmented-control'
import type { MeuUpdateChannel } from '@/global'
import { useI18n } from '@/i18n'
import { openExternalLink } from '@/lib/external-link'
import { confirm } from '@/store/confirm'
import { notifyError } from '@/store/notifications'
import { $updateChecking, $updateStatus, setMeuUpdateChannel } from '@/store/updates'

import { ListRow } from './primitives'

/**
 * Meu builds only: the stable/RC preference. Stable is the default; RC is opt-in with a warning and
 * never installs anything by itself — RC builds are published privately and installed manually.
 */
export function MeuUpdateChannelRow(): ReactElement | null {
  const { t } = useI18n()
  const a = t.settings.about.channel
  const status = useStore($updateStatus)
  const checking = useStore($updateChecking)
  const [pending, setPending] = useState<MeuUpdateChannel | null>(null)

  if (!status?.meuChannel) {
    return null
  }

  const channel = pending ?? status.meuChannelPreference ?? status.meuChannel

  const change = async (next: MeuUpdateChannel): Promise<void> => {
    if (next === channel) {
      return
    }

    if (
      next === 'rc' &&
      !(await confirm({ title: a.rcConfirmTitle, description: a.rcWarning, confirmLabel: a.rcConfirm }))
    ) {
      return
    }

    setPending(next)

    try {
      await setMeuUpdateChannel(next)
    } catch (error) {
      notifyError(error, a.failed)
    } finally {
      setPending(null)
    }
  }

  const releases = status.rcReleasesUrl

  return (
    <ListRow
      action={
        <SegmentedControl
          disabled={checking || pending !== null}
          onChange={id => void change(id)}
          options={[
            { id: 'stable', label: a.meuStable },
            { id: 'rc', label: a.meuRc }
          ]}
          value={channel}
        />
      }
      description={
        <>
          {channel === 'rc' ? `${a.rcWarning} ${a.rcManual}` : a.meuDescription}
          {releases && (
            <Button className="ml-1 h-auto p-0" onClick={() => openExternalLink(releases)} size="sm" variant="link">
              {a.rcReleases}
            </Button>
          )}
        </>
      }
      title={a.title}
    />
  )
}
