import { useEffect, useRef, useState } from 'react'

import { hermesApi } from '@/api/client'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/context'

interface FolderState {
  enabled: boolean
  directory?: string
}

export function TransferFolderSettings({ profile }: { profile?: string }) {
  const { locale } = useI18n()
  const greek = locale === 'el'
  const [folder, setFolder] = useState<FolderState>()
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const live = useRef(true)
  const generation = useRef(0)
  const read = () => hermesApi<FolderState>({ connectionId: 'local', profile, path: '/api/meu-transfers' })

  useEffect(() => {
    live.current = true
    const epoch = ++generation.current
    setBusy(true)
    void read()
      .then(value => {
        if (live.current && generation.current === epoch) setFolder(value)
      })
      .catch(() => {
        if (live.current && generation.current === epoch)
          setError(greek ? 'Ο φάκελος δεν διαβάστηκε. Δοκίμασε ξανά.' : 'Could not read the folder. Try again.')
      })
      .finally(() => {
        if (live.current && generation.current === epoch) setBusy(false)
      })
    return () => {
      live.current = false
      generation.current++
    }
  }, [profile])

  async function select(disable = false) {
    const epoch = generation.current
    setBusy(true)
    setError('')
    try {
      const paths = disable ? [''] : await window.hermesDesktop?.selectPaths({ directories: true, multiple: false })
      if (!paths?.length || !live.current || generation.current !== epoch) return
      const value = await hermesApi<FolderState>({
        connectionId: 'local',
        profile,
        path: '/api/meu-transfers/folder',
        method: 'POST',
        body: { directory: paths[0] }
      })
      if (live.current && generation.current === epoch) setFolder(value)
    } catch {
      if (live.current && generation.current === epoch)
        setError(greek ? 'Η επιλογή φακέλου απέτυχε.' : 'Could not change the transfer folder.')
    } finally {
      if (live.current && generation.current === epoch) setBusy(false)
    }
  }

  return (
    <section className="mt-4 space-y-3 rounded-md border p-4">
      <h3 className="text-sm font-medium">{greek ? 'Μεταφορά αρχείων PC–κινητού' : 'PC–phone file transfers'}</h3>
      <p className="text-xs text-muted-foreground">
        {greek
          ? 'Η συνδεδεμένη εφαρμογή μπορεί να περιηγείται σε αυτόν τον φάκελο και τους υποφακέλους του και να μεταφέρει αρχεία. Τα υπάρχοντα αρχεία δεν αντικαθίστανται.'
          : 'Your connected phone can browse this folder and its subfolders and transfer files. Existing files are never overwritten.'}
      </p>
      <p className="break-all text-xs">
        {folder?.enabled ? folder.directory : greek ? 'Δεν έχει επιλεγεί φάκελος.' : 'No folder selected.'}
      </p>
      <div className="flex gap-2">
        <Button disabled={busy} onClick={() => void select()} size="sm" variant="outline">
          {greek ? 'Επιλογή φακέλου' : 'Choose folder'}
        </Button>
        {folder?.enabled && (
          <Button disabled={busy} onClick={() => void select(true)} size="sm" variant="outline">
            {greek ? 'Διακοπή κοινής χρήσης' : 'Stop sharing'}
          </Button>
        )}
        {error && (
          <Button
            disabled={busy}
            onClick={() => {
              const epoch = generation.current
              setBusy(true)
              void read()
                .then(value => {
                  if (live.current && generation.current === epoch) {
                    setFolder(value)
                    setError('')
                  }
                })
                .catch(() => {
                  if (live.current && generation.current === epoch)
                    setError(greek ? 'Ο φάκελος δεν διαβάστηκε.' : 'Could not read the folder.')
                })
                .finally(() => {
                  if (live.current && generation.current === epoch) setBusy(false)
                })
            }}
            size="sm"
            variant="outline"
          >
            {greek ? 'Επανάληψη' : 'Retry'}
          </Button>
        )}
      </div>
      {error && (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
