import type { ProjectMemorySnapshot } from '@hermes/shared'
import { useStore } from '@nanostores/react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Loader } from '@/components/ui/loader'
import { Textarea } from '@/components/ui/textarea'
import { useI18n } from '@/i18n'
import { isMissingRpcMethod } from '@/lib/gateway-rpc'
import { $activeConnectionId } from '@/store/connections'
import { shouldOfferLocalReveal } from '@/store/file-actions'
import { $activeGatewayProfile } from '@/store/profile'
import { projectMemoryClient, revealPath } from '@/store/projects'

import type { SidebarProjectTree } from './workspace-groups'

export function ProjectMemory({ project }: { project: SidebarProjectTree }) {
  const connection = useStore($activeConnectionId)
  const profile = useStore($activeGatewayProfile)

  return <ProjectMemoryButton key={`${connection}:${profile}:${project.id}`} project={project} />
}

function ProjectMemoryButton({ project }: { project: SidebarProjectTree }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)

  return (
    <>
      <Button className="mx-2 mb-2" onClick={() => setOpen(true)} size="xs" variant="ghost">
        {t.projectMemory.title}
      </Button>
      <Dialog onOpenChange={setOpen} open={open}>
        {open && <ProjectMemoryEditor project={project} />}
      </Dialog>
    </>
  )
}

function ProjectMemoryEditor({ project }: { project: SidebarProjectTree }) {
  const { t } = useI18n()
  const m = t.projectMemory
  const connection = useStore($activeConnectionId)
  const client = useRef<Awaited<ReturnType<typeof projectMemoryClient>> | null>(null)
  const [data, setData] = useState<ProjectMemorySnapshot | null>(null)
  const [editor, setEditor] = useState<{ id?: string; content: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  const showError = (reason: unknown) => {
    setError(isMissingRpcMethod(reason) ? m.unavailable : reason instanceof Error ? reason.message : String(reason))
  }

  const load = async (isCurrent: () => boolean = () => true) => {
    setBusy(true)
    setError('')
    setSaved(false)

    try {
      const api = client.current ?? (await projectMemoryClient(project.id))
      client.current = api
      const result = await api.load()

      if (isCurrent()) {
        setData(result)
        setEditor(null)
      }
    } catch (reason) {
      if (isCurrent()) {
        showError(reason)
      }
    } finally {
      if (isCurrent()) {
        setBusy(false)
      }
    }
  }

  useEffect(() => {
    let active = true
    void load(() => active)

    return () => {
      active = false
    }
    // The owning project/profile/connection remounts this editor; do not reload over a draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const update = async (action: 'add' | 'patch' | 'remove', id?: string, content?: string) => {
    if (!data || !client.current) {
      return
    }

    setBusy(true)
    setError('')
    setSaved(false)

    try {
      const result = await client.current.update({ action, note_id: id, content, revision: data.revision })

      if (!result.saved) {
        throw new Error(result.error ?? 'The note was not saved.')
      }

      setData(result.memory)
      setEditor(null)
      setSaved(true)
    } catch (reason) {
      showError(reason)
    } finally {
      setBusy(false)
    }
  }

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>
          {m.title} · {project.label}
        </DialogTitle>
        <DialogDescription>{m.description}</DialogDescription>
      </DialogHeader>
      <div aria-busy={busy} className="min-w-0 space-y-3">
        {busy && <Loader className="size-5" label={t.common.loading} />}
        {error && (
          <p className="text-destructive" role="alert">
            {error}
          </p>
        )}
        {saved && <p role="status">{m.saved}</p>}
        <Button disabled={busy} onClick={() => void load()} size="sm" variant="ghost">
          {t.common.refresh}
        </Button>
        {data && !data.enabled && <p>{m.disabled}</p>}
        {data?.enabled && (
          <>
            <p className="break-all text-xs text-(--ui-text-secondary)">{data.path}</p>
            {data.path && shouldOfferLocalReveal(connection) && (
              <Button onClick={() => void revealPath(data.path!)} size="sm" variant="ghost">
                {m.openFolder}
              </Button>
            )}
            {data.entries.length === 0 && <p>{m.empty}</p>}
            <ul className="space-y-3">
              {data.entries.map(note => (
                <li className="space-y-1" key={note.id}>
                  <p className="whitespace-pre-wrap break-words">{note.content}</p>
                  <Button
                    disabled={busy}
                    onClick={() => {
                      setEditor(note)
                      setSaved(false)
                    }}
                    size="xs"
                    variant="ghost"
                  >
                    {m.edit}
                  </Button>
                  <Button disabled={busy} onClick={() => void update('remove', note.id)} size="xs" variant="ghost">
                    {m.remove}
                  </Button>
                </li>
              ))}
            </ul>
            {!editor && (
              <Button
                disabled={busy}
                onClick={() => {
                  setEditor({ content: '' })
                  setSaved(false)
                }}
                size="sm"
                variant="secondary"
              >
                {m.add}
              </Button>
            )}
            {editor && (
              <div className="space-y-2">
                <Textarea
                  aria-label={m.note}
                  disabled={busy}
                  onChange={e => setEditor({ ...editor, content: e.target.value })}
                  value={editor.content}
                />
                <Button
                  disabled={busy || !editor.content.trim()}
                  onClick={() => void update(editor.id ? 'patch' : 'add', editor.id, editor.content)}
                  size="sm"
                >
                  {t.common.save}
                </Button>
                <Button disabled={busy} onClick={() => setEditor(null)} size="sm" variant="ghost">
                  {t.common.cancel}
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </DialogContent>
  )
}
