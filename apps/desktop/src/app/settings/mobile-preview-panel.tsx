import { useStore } from '@nanostores/react'
import { useEffect, useState } from 'react'

import { $apiRequestScope, hermesApi } from '@/api/client'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/context'

type Pairing = { state: 'off' | 'waiting' | 'paired' | 'other-profile'; code?: string | null; seconds?: number }
const PAIRING_PATH = '/api/mobile-preview'

export function MobilePreviewPanel() {
  const { profile } = useStore($apiRequestScope)

  return <PairingControls key={profile ?? 'default'} profile={profile ?? undefined} />
}

function PairingControls({ profile }: { profile?: string }) {
  const { t } = useI18n()
  const [pairing, setPairing] = useState<Pairing>()
  const [qr, setQr] = useState<{ code: string; image: string }>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [remote, setRemote] = useState(false)

  const active = pairing?.state === 'waiting' || pairing?.state === 'paired'
  useEffect(() => {
    let current = true
    let timer: number | undefined

    const read = async () => {
      try {
        const result = await hermesApi<Pairing>({
          connectionId: 'local', path: PAIRING_PATH, profile, passive: true, timeoutMs: 4000
        })

        if (current) {
          setPairing(result)
        }
      } catch {
        // Keep the pairing visible during a transient poll failure.
      } finally {
        if (current && active) {
          timer = window.setTimeout(() => void read(), 1500)
        }
      }
    }

    if (!busy) {
      void read()
    }

    return () => {
      current = false
      window.clearTimeout(timer)
    }
  }, [active, busy, profile])

  useEffect(() => {
    let current = true
    if (pairing?.code) {
      const code = pairing.code

      void import('qrcode')
        .then(({ toDataURL }) => toDataURL(code, { width: 320, margin: 4, errorCorrectionLevel: 'M' }))
        .then(image => {
          if (current) {
            setQr({ code, image })
          }
        })
        .catch(() => {
          if (current) {
            setError('Meu could not draw the pairing code. Disconnect and try again.')
          }
        })
    }

    return () => { current = false }
  }, [pairing?.code])

  async function change(method: 'POST' | 'DELETE') {
    const remoteStart = method === 'POST' && remote

    setBusy(true)
    setError('')

    try {
      const path = remoteStart ? `${PAIRING_PATH}/tailscale` : PAIRING_PATH
      setPairing(await hermesApi<Pairing>({ connectionId: 'local', path, profile, method }))
    } catch {
      setError(remoteStart ? t.settings.gateway.mobileRemoteError : method === 'POST'
        ? 'Pairing could not start. Check that the local Meu backend is running and this computer is on a private network.'
        : 'Meu could not disconnect the phone. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const minutes = Math.max(1, Math.ceil((pairing?.seconds ?? 0) / 60))

  return (
    <section aria-labelledby="mobile-pairing-title" className="mt-6 rounded-xl border border-border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid gap-1">
          <h3 className="text-sm font-semibold" id="mobile-pairing-title">Connect a phone</h3>
          <p className="text-xs text-muted-foreground">{t.settings.gateway.mobileNetworkHint}</p>
          {!active && pairing?.state !== 'other-profile' && (
            <label className="flex items-center gap-2 text-xs">
              <input checked={remote} disabled={busy} onChange={event => setRemote(event.target.checked)} type="checkbox" />
              {t.settings.gateway.mobileRemote}
            </label>
          )}
        </div>
        <Button disabled={busy || pairing?.state === 'other-profile'} onClick={() => void change(active ? 'DELETE' : 'POST')} size="sm">
          {active ? 'Disconnect phone' : 'Show pairing code'}
        </Button>
      </div>
      {pairing?.state === 'waiting' && (
        <div className="mt-4 grid justify-items-start gap-2">
          <p className="text-xs">Open Meu on your phone, choose <strong>Scan pairing code</strong> and point the camera here.</p>
          {qr && qr.code === pairing.code && <img alt="Meu pairing QR code" className="aspect-square w-72 max-w-full rounded-lg bg-white" src={qr.image} />}
          <p className="text-xs text-muted-foreground">This code can be used once and expires in about {minutes} min.</p>
        </div>
      )}
      {pairing?.state === 'paired' && <p className="mt-3 text-xs text-primary" role="status">Phone connected · about {minutes} min remaining</p>}
      {pairing?.state === 'other-profile' && <p className="mt-3 text-xs text-muted-foreground">Switch to the paired profile to manage its phone connection.</p>}
      {error && <p className="mt-3 text-xs text-destructive" role="alert">{error}</p>}
    </section>
  )
}
