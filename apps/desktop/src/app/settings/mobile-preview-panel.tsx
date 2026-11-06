import { useStore } from '@nanostores/react'
import { useEffect, useState } from 'react'

import { $apiRequestScope, hermesApi } from '@/api/client'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/context'
import { writeClipboardText } from '@/lib/clipboard'
import type { PaginatedSessions, SessionInfo } from '@/types/hermes'

type Pairing = { state: 'off' | 'waiting' | 'paired' | 'other-profile'; code?: string | null; seconds?: number | null; sync?: boolean; sync_profile?: boolean; offline?: boolean }
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
  const [copiedCode, setCopiedCode] = useState<string>()
  const [sync, setSync] = useState(false)
  const [sessionId, setSessionId] = useState('')
  const [wholeProfile, setWholeProfile] = useState(false)
  const [sessions, setSessions] = useState<SessionInfo[]>()
  const [sessionListFailed, setSessionListFailed] = useState(false)

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
    if (!sync || wholeProfile || active) {
      return
    }

    let current = true
    setSessions(undefined)
    setSessionListFailed(false)
    const params = new URLSearchParams({ limit: '40', min_messages: '1', archived: 'exclude', order: 'recent' })
    if (profile) {
      params.set('profile', profile)
    }
    void hermesApi<PaginatedSessions>({
      connectionId: 'local', path: `/api/sessions?${params}`, profile, timeoutMs: 8000
    }).then(result => {
      if (current) {
        const eligible = result.sessions.filter(session =>
          !session.parent_session_id && session.continuation_kind !== 'compression' &&
          /^(?:[0-9]{8}_[0-9]{6}_[0-9a-f]{6,12}|local-[0-9a-f]{64})$/.test(session.id)
        )
        setSessions(eligible)
        setSessionId(id => eligible.some(session => session.id === id) ? id : '')
      }
    }).catch(() => {
      if (current) {
        setSessionListFailed(true)
      }
    })

    return () => { current = false }
  }, [active, profile, sync, wholeProfile])

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
    const syncStart = method === 'POST' && sync
    const profileStart = syncStart && wholeProfile
    const remoteStart = method === 'POST' && remote && !sync
    if (syncStart && !profileStart && !sessions?.some(session => session.id === sessionId)) {
      return
    }

    setBusy(true)
    setError('')

    try {
      const path = profileStart ? `${PAIRING_PATH}/sync/profile` : syncStart ? `${PAIRING_PATH}/sync` : remoteStart ? `${PAIRING_PATH}/internet` : PAIRING_PATH
      setPairing(await hermesApi<Pairing>({
        connectionId: 'local', path, profile, method,
        ...(syncStart && !profileStart ? { body: { session_id: sessionId } } : {})
      }))
    } catch {
      setError(profileStart ? 'Profile sync pairing could not start. Check the PC network.'
        : syncStart ? 'Sync pairing could not start. Select a supported conversation and check the PC network.'
        : remoteStart ? t.settings.gateway.mobileRemoteError : method === 'POST'
        ? 'Pairing could not start. Check that the local Meu backend is running and this computer is on a private network.'
        : 'Meu could not disconnect the phone. Try again.')
    } finally {
      setBusy(false)
    }
  }

  async function copyPairingCode(code: string) {
    try {
      await writeClipboardText(code)
      setCopiedCode(code)
    } catch {
      setError('Could not copy the pairing code.')
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
            <>
              <label className="flex items-center gap-2 text-xs">
                <input checked={sync} disabled={busy} onChange={event => setSync(event.target.checked)} type="checkbox" />
                Sync conversation history via Wi-Fi or Tailscale
              </label>
              {sync && (
                <label className="flex items-center gap-2 text-xs">
                  <input checked={wholeProfile} disabled={busy} onChange={event => setWholeProfile(event.target.checked)} type="checkbox" />
                  Sync all supported conversations in this profile
                </label>
              )}
              {sync && !wholeProfile ? (
                <label className="grid gap-1 text-xs">
                  Conversation to share
                  <select
                    className="rounded-md border border-border bg-background p-1"
                    disabled={busy || !sessions?.length}
                    onChange={event => setSessionId(event.target.value)}
                    value={sessionId}
                  >
                    <option value="">{sessionListFailed ? 'Could not load conversations' : sessions === undefined
                      ? 'Loading conversations…' : sessions.length === 0 ? 'No eligible conversations' : 'Select a conversation'}</option>
                    {sessions?.map(session => <option key={session.id} value={session.id}>
                      {session.title || session.preview || session.id}
                    </option>)}
                  </select>
                </label>
              ) : !sync ? (
                <label className="flex items-center gap-2 text-xs">
                  <input checked={remote} disabled={busy} onChange={event => setRemote(event.target.checked)} type="checkbox" />
                  {t.settings.gateway.mobileRemote}
                </label>
              ) : null}
            </>
          )}
        </div>
        <Button disabled={busy || pairing?.state === 'other-profile' || (!active && sync && !wholeProfile && !sessions?.some(session => session.id === sessionId))} onClick={() => void change(active ? 'DELETE' : 'POST')} size="sm">
          {active ? 'Disconnect phone' : 'Show pairing code'}
        </Button>
      </div>
      {pairing?.state === 'waiting' && (
        <div className="mt-4 grid justify-items-start gap-2">
          {pairing.sync
            ? <p className="text-xs">Open Sync with PC in Meu Mobile and scan this QR code or paste the pairing code.</p>
            : <p className="text-xs">Open Meu on your phone, choose <strong>Scan pairing code</strong> and point the camera here.</p>}
          {pairing.sync && pairing.code && (
            <Button onClick={() => void copyPairingCode(pairing.code!)} size="sm" variant="outline">
              {copiedCode === pairing.code ? 'Code copied' : 'Copy pairing code'}
            </Button>
          )}
          {qr && qr.code === pairing.code && <img alt="Meu pairing QR code" className="aspect-square w-72 max-w-full rounded-lg bg-white" src={qr.image} />}
          <p className="text-xs text-muted-foreground">This code can be used once and expires in about {minutes} min.</p>
        </div>
      )}
      {pairing?.state === 'paired' && <p className="mt-3 text-xs text-primary" role="status">{pairing.sync_profile ? (pairing.offline ? 'Phone paired · waiting for network' : 'Phone paired for profile sync') : `Phone connected · about ${minutes} min remaining`}</p>}
      {pairing?.state === 'other-profile' && <p className="mt-3 text-xs text-muted-foreground">Switch to the paired profile to manage its phone connection.</p>}
      {error && <p className="mt-3 text-xs text-destructive" role="alert">{error}</p>}
    </section>
  )
}
