import { useEffect, useState } from 'react'

import { hermesApi } from '@/api/client'
import { Button } from '@/components/ui/button'
import { writeClipboardText } from '@/lib/clipboard'

interface PersonalDevice {
  id: string
  space_id: string
  label: string
  paired: boolean
  state: 'off' | 'waiting' | 'paired'
  last_contact: string | null
}
interface DeviceList {
  spaces: { id: string; name: string }[]
  devices: PersonalDevice[]
}
interface Enrolment {
  device_id: string
  space_name: string
  code: string
}
const PATH = '/api/mobile-preview/devices'

export function PersonalDevicesSettings({ profile }: { profile?: string }) {
  return <PersonalDevicesControls key={profile ?? 'default'} profile={profile} />
}

function PersonalDevicesControls({ profile }: { profile?: string }) {
  const [data, setData] = useState<DeviceList>()
  const [selected, setSelected] = useState('')
  const [name, setName] = useState('')
  const [label, setLabel] = useState('')
  const [enrolment, setEnrolment] = useState<Enrolment>()
  const [qr, setQr] = useState<{ code: string; image: string }>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    let current = true
    let timer: ReturnType<typeof setTimeout>

    const read = async () => {
      try {
        const result = await hermesApi<DeviceList>({
          connectionId: 'local',
          path: PATH,
          profile,
          passive: true,
          timeoutMs: 4000
        })

        if (current && Array.isArray(result.spaces) && Array.isArray(result.devices)) {
          setData(result)

          if (enrolment && !result.devices.some(d => d.id === enrolment.device_id && d.state === 'waiting')) {
            setEnrolment(undefined)
          }
        }
      } catch {
        // Keep the last device list during a transient outage. Mutations report their own refusal.
      } finally {
        if (current) {
          timer = setTimeout(() => void read(), 4000)
        }
      }
    }

    void read()

    return () => {
      current = false
      clearTimeout(timer)
    }
  }, [enrolment, profile, revision])

  useEffect(() => {
    let current = true
    setQr(undefined)

    if (enrolment) {
      const code = enrolment.code
      void import('qrcode')
        .then(module => module.toDataURL(code, { width: 260, margin: 2 }))
        .then(image => {
          if (current) {
            setQr({ code, image })
          }
        })
        .catch(() => {
          if (current) {
            setError('The QR could not be drawn. Copy the pairing code instead.')
          }
        })
    }

    return () => {
      current = false
    }
  }, [enrolment])

  async function add() {
    setBusy(true)
    setError('')

    try {
      const result = await hermesApi<Enrolment>({
        connectionId: 'local',
        method: 'POST',
        path: PATH,
        profile,
        body: {
          ...(selected ? { space_id: selected } : { name: name.trim() }),
          ...(label.trim() ? { label: label.trim() } : {})
        }
      })

      setEnrolment(result)
      setName('')
      setLabel('')
      setRevision(r => r + 1)
    } catch {
      setError(
        'Could not add the device. Select a shared folder first. Use a new folder name or select an existing user.'
      )
    } finally {
      setBusy(false)
    }
  }

  async function remove(id: string) {
    setBusy(true)
    setError('')

    try {
      await hermesApi({ connectionId: 'local', method: 'DELETE', path: `${PATH}/${encodeURIComponent(id)}`, profile })

      setData(value => value && { ...value, devices: value.devices.filter(d => d.id !== id) })

      if (enrolment?.device_id === id) {
        setEnrolment(undefined)
      }
      setRevision(r => r + 1)
    } catch {
      setError('The device was not disconnected. Check the PC connection and retry.')
    } finally {
      setBusy(false)
    }
  }

  // Older gateways retain their existing pairing controls; no fallback widens a personal grant.
  if (!data) {
    return null
  }

  return (
    <section aria-labelledby="personal-devices-title" className="mt-6 rounded-xl border border-border p-4">
      <h3 className="text-sm font-semibold" id="personal-devices-title">
        Users and devices
      </h3>
      <p className="mt-2 text-xs text-muted-foreground">
        Each name or nickname creates its own folder inside your selected shared folder. Devices of the same user share
        that space. This pairing syncs that user’s conversation history and files. The PC owner can see all spaces.
      </p>
      <div className="my-4 grid gap-3 sm:grid-cols-2">
        <label className="text-xs">
          Personal space
          <select
            className="mt-1 block w-full rounded border bg-background p-2"
            disabled={busy}
            onChange={e => setSelected(e.target.value)}
            value={selected}
          >
            <option value="">New user</option>
            {data.spaces.map(space => (
              <option key={space.id} value={space.id}>
                {space.name}
              </option>
            ))}
          </select>
        </label>
        {!selected && (
          <label className="text-xs">
            Name / nickname
            <input
              className="mt-1 block w-full rounded border bg-background p-2"
              disabled={busy}
              maxLength={80}
              onChange={e => setName(e.target.value)}
              value={name}
            />
          </label>
        )}
        <label className="text-xs">
          Device name (optional)
          <input
            className="mt-1 block w-full rounded border bg-background p-2"
            disabled={busy}
            maxLength={80}
            onChange={e => setLabel(e.target.value)}
            placeholder="My phone"
            value={label}
          />
        </label>
      </div>
      <Button disabled={busy || (!selected && !name.trim()) || !!enrolment} onClick={() => void add()} size="sm">
        Add device · show QR
      </Button>
      {error && (
        <p className="mt-2 text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
      {enrolment && (
        <div className="mt-3 text-xs">
          <p>Open Sync with PC in Meu Mobile and scan once to connect to {enrolment.space_name}.</p>
          {qr?.code === enrolment.code && (
            <img alt="Personal device pairing QR" height={260} src={qr.image} width={260} />
          )}
          <Button
            onClick={() => void writeClipboardText(enrolment.code).catch(() => setError('Could not copy the code.'))}
            size="sm"
            variant="outline"
          >
            Copy personal pairing code
          </Button>
          <p className="mt-2 text-muted-foreground">
            The QR expires after five minutes. Each paired device keeps its own connection after restarting.
          </p>
        </div>
      )}
      <ul className="mt-4 space-y-3">
        {data.devices.map(device => (
          <li className="flex items-center justify-between gap-3 rounded border p-3 text-xs" key={device.id}>
            <div>
              <strong>{device.label}</strong> · {data.spaces.find(s => s.id === device.space_id)?.name}
              <p className="mt-1 text-muted-foreground">
                {device.state === 'waiting' ? 'Waiting for scan' : device.paired ? 'Paired' : 'Pairing expired'}
                {device.last_contact && ` · Last seen ${new Date(device.last_contact).toLocaleString()}`}
              </p>
            </div>
            <Button disabled={busy} onClick={() => void remove(device.id)} size="sm" variant="outline">
              Disconnect {device.label}
            </Button>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-muted-foreground">
        Disconnecting a device keeps its user’s folder and history. Select that user when pairing a replacement.
      </p>
    </section>
  )
}
