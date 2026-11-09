import { useState } from 'react'

import { hermesApi } from '@/api/client'
import { Button } from '@/components/ui/button'

interface Props {
  profile?: string
  legacy: { state: string; can_migrate: boolean }
  owner?: string
  onChanged: (spaceId?: string) => void
}

export function LegacyDeviceMigration({ profile, legacy, owner, onChanged }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [name, setName] = useState('')
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function change(migrate: boolean) {
    setBusy(true)
    setError('')
    try {
      const result = await hermesApi<{ space_id?: string }>({
        connectionId: 'local',
        profile,
        method: migrate ? 'POST' : 'DELETE',
        path: migrate ? '/api/mobile-preview/devices/migrate' : '/api/mobile-preview',
        ...(migrate
          ? { body: { ...(!owner ? { name: name.trim() } : {}), ...(label.trim() ? { label: label.trim() } : {}) } }
          : {})
      })
      setExpanded(false)
      onChanged(result.space_id)
    } catch {
      setError('The change did not finish. Existing connections, conversations and files were kept. Refresh and retry.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2 text-xs">
      <strong>Existing connection</strong>
      {legacy.state === 'other-profile' ? (
        <p>Open the profile that owns this connection to manage it.</p>
      ) : (
        <>
          <p className="text-muted-foreground">
            {legacy.can_migrate
              ? 'Keep this connection without scanning again. Its owner access, conversations and file paths stay the same.'
              : 'Your previous temporary connection remains available until it expires or you disconnect it. Saved conversations and files stay on the PC.'}
          </p>
          {legacy.can_migrate && !expanded && (
            <Button size="sm" variant="outline" onClick={() => setExpanded(true)}>
              Keep existing connection
            </Button>
          )}
          {expanded && (
            <div className="grid gap-2">
              {owner ? (
                <p>Owner: {owner}</p>
              ) : (
                <label>
                  Your name / nickname
                  <input
                    className="ml-2 rounded border bg-background p-1"
                    maxLength={80}
                    value={name}
                    disabled={busy}
                    onChange={event => setName(event.target.value)}
                  />
                </label>
              )}
              <label>
                Existing device name (optional)
                <input
                  className="ml-2 rounded border bg-background p-1"
                  maxLength={80}
                  value={label}
                  disabled={busy}
                  onChange={event => setLabel(event.target.value)}
                />
              </label>
              <div className="flex gap-2">
                <Button size="sm" disabled={busy || (!owner && !name.trim())} onClick={() => void change(true)}>
                  Finish migration
                </Button>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => setExpanded(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void change(false)}>
            Disconnect existing connection
          </Button>
        </>
      )}
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}
