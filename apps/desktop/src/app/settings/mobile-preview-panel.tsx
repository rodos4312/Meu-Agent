import { useStore } from '@nanostores/react'
import { useEffect, useState } from 'react'

import { $apiRequestScope, hermesApi } from '@/api/client'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/context'
import { writeClipboardText } from '@/lib/clipboard'
import type { PaginatedSessions, SessionInfo } from '@/types/hermes'
import { TransferFolderSettings } from './transfer-folder-settings'
import { PersonalDevicesSettings } from './personal-devices-settings'

interface Pairing {
  state: 'off' | 'waiting' | 'paired' | 'other-profile'
  code?: string | null
  seconds?: number | null
  sync?: boolean
  sync_profile?: boolean
  offline?: boolean
  listener_count?: number
  last_contact?: string | null
}
const PAIRING_PATH = '/api/mobile-preview'

export function MobilePreviewPanel() {
  const { profile } = useStore($apiRequestScope)

  return (
    <div key={profile ?? 'default'}>
      <PairingControls profile={profile ?? undefined} />
      <TransferFolderSettings profile={profile ?? undefined} />
      <PersonalDevicesSettings profile={profile ?? undefined} />
    </div>
  )
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
  const [statusUnavailable, setStatusUnavailable] = useState(false)
  const [statusRetry, setStatusRetry] = useState(0)

  const active = pairing?.state === 'waiting' || pairing?.state === 'paired'
  useEffect(() => {
    let current = true
    let timer: number | undefined

    const read = async () => {
      try {
        const result = await hermesApi<Pairing>({
          connectionId: 'local',
          path: PAIRING_PATH,
          profile,
          passive: true,
          timeoutMs: 4000
        })

        if (current) {
          setPairing(result)
          setStatusUnavailable(false)
        }
      } catch {
        // Keep the pairing visible during a transient poll failure.
        if (current) {
          setStatusUnavailable(true)
        }
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
  }, [active, busy, profile, statusRetry])

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
      connectionId: 'local',
      path: `/api/sessions?${params}`,
      profile,
      timeoutMs: 8000
    })
      .then(result => {
        if (current) {
          const eligible = result.sessions.filter(
            session =>
              !session.parent_session_id &&
              session.continuation_kind !== 'compression' &&
              /^(?:[0-9]{8}_[0-9]{6}_[0-9a-f]{6,12}|local-[0-9a-f]{64})$/.test(session.id)
          )

          setSessions(eligible)
          setSessionId(id => (eligible.some(session => session.id === id) ? id : ''))
        }
      })
      .catch(() => {
        if (current) {
          setSessionListFailed(true)
        }
      })

    return () => {
      current = false
    }
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

    return () => {
      current = false
    }
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
      const path = profileStart
        ? `${PAIRING_PATH}/sync/profile`
        : syncStart
          ? `${PAIRING_PATH}/sync`
          : remoteStart
            ? `${PAIRING_PATH}/internet`
            : PAIRING_PATH

      setPairing(
        await hermesApi<Pairing>({
          connectionId: 'local',
          path,
          profile,
          method,
          ...(syncStart && !profileStart ? { body: { session_id: sessionId } } : {})
        })
      )
      setStatusUnavailable(false)
    } catch {
      setError(
        profileStart
          ? 'Profile sync pairing could not start. Check the PC network.'
          : syncStart
            ? 'Sync pairing could not start. Select a supported conversation and check the PC network.'
            : remoteStart
              ? t.settings.gateway.mobileRemoteError
              : method === 'POST'
                ? 'Pairing could not start. Check that the local Meu backend is running and this computer is on a private network.'
                : 'Meu could not disconnect the phone. Try again.'
      )
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
          <h3 className="text-sm font-semibold" id="mobile-pairing-title">
            {t.settings.gateway.mobileConnectTitle}
          </h3>
          <p className="text-xs text-muted-foreground">{t.settings.gateway.mobileNetworkHint}</p>
          {!active && pairing?.state !== 'other-profile' && (
            <>
              <fieldset className="mt-3 grid gap-3 sm:grid-cols-2" disabled={busy}>
                <legend className="mb-2 text-xs font-medium">{t.settings.gateway.mobilePurpose}</legend>
                <label className="flex cursor-pointer items-start gap-2 text-xs">
                  <input
                    checked={!sync}
                    className="mt-0.5"
                    name="mobile-purpose"
                    onChange={() => setSync(false)}
                    type="radio"
                  />
                  <span className="grid gap-1">
                    <span className="font-medium">{t.settings.gateway.mobileControlTitle}</span>
                    <span className="text-muted-foreground">{t.settings.gateway.mobileControlHint}</span>
                  </span>
                </label>
                <label className="flex cursor-pointer items-start gap-2 text-xs">
                  <input
                    checked={sync}
                    className="mt-0.5"
                    name="mobile-purpose"
                    onChange={() => setSync(true)}
                    type="radio"
                  />
                  <span className="grid gap-1">
                    <span className="font-medium">{t.settings.gateway.mobileHistoryTitle}</span>
                    <span className="text-muted-foreground">{t.settings.gateway.mobileHistoryHint}</span>
                  </span>
                </label>
              </fieldset>
              {sync && (
                <label className="flex items-center gap-2 text-xs">
                  <input
                    checked={wholeProfile}
                    disabled={busy}
                    onChange={event => setWholeProfile(event.target.checked)}
                    type="checkbox"
                  />
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
                    <option value="">
                      {sessionListFailed
                        ? 'Could not load conversations'
                        : sessions === undefined
                          ? 'Loading conversations…'
                          : sessions.length === 0
                            ? 'No eligible conversations'
                            : 'Select a conversation'}
                    </option>
                    {sessions?.map(session => (
                      <option key={session.id} value={session.id}>
                        {session.title || session.preview || session.id}
                      </option>
                    ))}
                  </select>
                </label>
              ) : !sync ? (
                <label className="flex items-center gap-2 text-xs">
                  <input
                    checked={remote}
                    disabled={busy}
                    onChange={event => setRemote(event.target.checked)}
                    type="checkbox"
                  />
                  {t.settings.gateway.mobileRemote}
                </label>
              ) : null}
            </>
          )}
        </div>
        <Button
          disabled={
            busy ||
            pairing?.state === 'other-profile' ||
            (!active && sync && !wholeProfile && !sessions?.some(session => session.id === sessionId))
          }
          onClick={() => void change(active ? 'DELETE' : 'POST')}
          size="sm"
        >
          {active ? 'Disconnect phone' : 'Show pairing code'}
        </Button>
      </div>
      {active && (
        <p className="mt-3 text-xs text-muted-foreground">
          {pairing.sync || pairing.sync_profile
            ? t.settings.gateway.mobileHistoryHint
            : t.settings.gateway.mobileControlHint}
        </p>
      )}
      {pairing?.state === 'waiting' && (
        <div className="mt-4 grid justify-items-start gap-2">
          {pairing.sync || pairing.sync_profile ? (
            <p className="text-xs">Open Sync with PC in Meu Mobile and scan this QR code or paste the pairing code.</p>
          ) : (
            <p className="text-xs">
              Open Meu on your phone, choose <strong>Scan pairing code</strong> and point the camera here.
            </p>
          )}
          {(pairing.sync || pairing.sync_profile) && pairing.code && (
            <Button onClick={() => void copyPairingCode(pairing.code!)} size="sm" variant="outline">
              {copiedCode === pairing.code ? 'Code copied' : 'Copy pairing code'}
            </Button>
          )}
          {qr && qr.code === pairing.code && (
            <img
              alt="Meu pairing QR code"
              className="aspect-square w-72 max-w-full rounded-lg bg-white"
              src={qr.image}
            />
          )}
          <p className="text-xs text-muted-foreground">
            This code can be used once and expires in about {minutes} min.
          </p>
        </div>
      )}
      {!statusUnavailable && <PairingStatus minutes={minutes} pairing={pairing} />}
      {statusUnavailable && (
        <div className="mt-3 flex flex-wrap items-center gap-2" role="status">
          <p className="text-xs text-muted-foreground">{t.settings.gateway.mobileStatusUnavailable}</p>
          <Button disabled={busy} onClick={() => setStatusRetry(value => value + 1)} size="sm" variant="outline">
            {t.settings.gateway.mobileRetryStatus}
          </Button>
        </div>
      )}
      {pairing?.state === 'other-profile' && (
        <p className="mt-3 text-xs text-muted-foreground">
          Switch to the paired profile to manage its phone connection.
        </p>
      )}
      {error && (
        <p className="mt-3 text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}

function PairingStatus({ pairing, minutes }: { pairing?: Pairing; minutes: number }) {
  const { t } = useI18n()

  if (!pairing) {
    return null
  }

  const active = pairing.state === 'waiting' || pairing.state === 'paired'

  const syncing = pairing.sync || pairing.sync_profile

  const pairedLabel = syncing
    ? pairing.offline || pairing.listener_count === 0
      ? t.settings.gateway.mobileSyncUnavailable
      : pairing.listener_count === undefined
        ? t.settings.gateway.mobilePairedHistory
        : t.settings.gateway.mobileSyncReady
    : `${t.settings.gateway.mobilePairedControl}${pairing.seconds && pairing.seconds > 0 ? ` · about ${minutes} min remaining` : ''}`

  return (
    <>
      {pairing.state === 'paired' && (
        <p className="mt-3 text-xs text-primary" role="status">
          {pairedLabel}
        </p>
      )}
      {active && syncing && pairing.listener_count !== undefined && (
        <p className="mt-2 text-xs text-muted-foreground">
          {pairing.last_contact
            ? `${t.settings.gateway.mobileLastContact} ${new Date(pairing.last_contact).toLocaleString()}`
            : t.settings.gateway.mobileNoContact}{' '}
          {t.settings.gateway.mobileSyncUnconfirmed}
        </p>
      )}
    </>
  )
}
