import { useEffect, useRef, useState } from 'react'

import { hermesApi } from '@/api/client'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/context'

interface Project {
  id: string
  name: string
  directory: string
  owner: string
  phase: string
  return_requested?: boolean
}
interface Catalog {
  projects: Project[]
  conversations: { id: string; title: string | null }[]
}

export function ProjectSyncSettings({ profile }: { profile?: string }) {
  const { locale } = useI18n()
  const el = locale === 'el'
  const [catalog, setCatalog] = useState<Catalog>()
  const [session, setSession] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const generation = useRef(0)
  const path = '/api/mobile-preview/projects'
  useEffect(() => {
    generation.current++
    let live = true
    const read = async () => {
      try {
        const value = await hermesApi<Catalog>({ connectionId: 'local', profile, path })
        if (!Array.isArray(value.projects) || !Array.isArray(value.conversations)) throw new Error('unsupported_projects')
        if (live) setCatalog(value)
      } catch { if (live) setError(el ? 'Δεν διαβάστηκαν τα έργα. Ίσως χρειάζεται ενημέρωση του κινητήρα.' : 'Could not load projects. The engine may need an update.') }
    }
    void read()
    const timer = setInterval(() => void read(), 5000)
    return () => { live = false; generation.current++; clearInterval(timer) }
  }, [profile, el])

  async function add() {
    const epoch = generation.current
    setBusy(true)
    setError('')
    try {
      const directories = await window.hermesDesktop?.selectPaths({ directories: true, multiple: false })
      if (!directories?.length || generation.current !== epoch) return
      const directory = directories[0]
      const name = directory.replace(/[/\\]+$/, '').split(/[/\\]/).pop()!
      await hermesApi({ connectionId: 'local', profile, path, method: 'POST', body: { directory, name, session_id: session } })
      const value = await hermesApi<Catalog>({ connectionId: 'local', profile, path })
      if (generation.current === epoch) setCatalog(value)
    } catch {
      if (generation.current === epoch) setError(el ? 'Το έργο δεν προστέθηκε. Ολοκλήρωσε την εργασία του agent και επίλεξε ξεχωριστό φάκελο έργου.' : 'Could not add this project. Finish the agent task and choose a separate project folder.')
    } finally { if (generation.current === epoch) setBusy(false) }
  }

  async function takeHere(id: string) {
    const epoch = generation.current
    setBusy(true)
    setError('')
    try {
      await hermesApi({ connectionId: 'local', profile, path: `${path}/${id}/return`, method: 'POST' })
      const value = await hermesApi<Catalog>({ connectionId: 'local', profile, path })
      if (generation.current === epoch) setCatalog(value)
    } catch { if (generation.current === epoch) setError(el ? 'Δεν στάλθηκε το αίτημα. Δοκίμασε ξανά.' : 'Could not request the project. Try again.') }
    finally { if (generation.current === epoch) setBusy(false) }
  }

  return <section className="mt-4 space-y-3 border-t pt-4">
    <h3 className="text-sm font-medium">{el ? 'Συνέχεια έργου σε PC και κινητό' : 'Continue a project on PC and phone'}</h3>
    <p className="text-xs text-muted-foreground">{el
      ? 'Σύνδεσε τη συνομιλία με τον φάκελο του έργου. Στο κινητό, άνοιξε Συγχρονισμός → Έργα και επίλεξε πού θα συνεχίσεις. Ένας agent εκτελεί το έργο κάθε φορά. Περίμενε την επιβεβαίωση πριν κλείσεις το PC.'
      : 'Link a conversation to its project folder. On your phone, open Sync → Projects and choose where to continue. Only one device executes the project. Wait for confirmation before shutting down the PC.'}</p>
    <select aria-label={el ? 'Συνομιλία έργου' : 'Project conversation'} value={session} onChange={event => setSession(event.target.value)} className="w-full bg-background text-sm">
      <option value="">{el ? 'Επίλεξε συνομιλία' : 'Choose a conversation'}</option>
      {catalog?.conversations.map(item => <option key={item.id} value={item.id}>{item.title || item.id}</option>)}
    </select>
    <Button size="sm" variant="outline" disabled={busy || !session} onClick={() => void add()}>{el ? 'Επιλογή φακέλου έργου' : 'Choose project folder'}</Button>
    {catalog?.projects.map(item => <div key={item.id} className="space-y-1 text-xs">
      <p className="font-medium">{item.name} · {item.phase === 'ready' && item.owner === 'pc' ? (el ? 'Εκτέλεση στο PC' : 'Runs on PC') : item.phase === 'released' ? (el ? 'Παραδόθηκε στο κινητό' : 'Handed to phone') : (el ? 'Μεταφορά σε εξέλιξη' : 'Transfer in progress')}</p>
      <p className="break-all text-muted-foreground">{item.directory}</p>
      {item.owner !== 'pc' && <Button size="sm" variant="outline" disabled={busy || item.return_requested} onClick={() => void takeHere(item.id)}>
        {item.return_requested ? (el ? 'Αναμονή παράδοσης από το κινητό' : 'Waiting for the phone to hand over') : (el ? 'Συνέχεια στο PC' : 'Continue on PC')}
      </Button>}
    </div>)}
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
  </section>
}
