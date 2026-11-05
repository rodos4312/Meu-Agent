import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { atom } from 'nanostores'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { projectMemoryClient, revealPath } from '@/store/projects'
import { deferred } from '@/test/deferred'

import { ProjectMemory } from './project-memory'
import type { SidebarProjectTree } from './workspace-groups'

const owner = vi.hoisted(() => ({ connection: null as unknown as ReturnType<typeof atom<string>> }))
vi.mock('@/store/projects', () => ({ projectMemoryClient: vi.fn(), revealPath: vi.fn() }))
vi.mock('@/store/connections', async () => {
  const { atom } = await import('nanostores')
  owner.connection = atom('local')

  return { $activeConnectionId: owner.connection }
})
vi.mock('@/store/profile', async () => {
  const { atom } = await import('nanostores')

  return { $activeGatewayProfile: atom('default') }
})
vi.mock('@/store/file-actions', () => ({ shouldOfferLocalReveal: () => true }))

const initial = {
  enabled: true,
  root: '/work',
  path: '/profile/memories/projects/key/PROJECT.md',
  revision: 'one',
  limit: 2200,
  entries: [{ id: 'png', content: 'Export PNG in A5.' }]
}

const project = { id: 'workspace', label: 'Birthday', path: '/work', repos: [], sessionCount: 0 } as SidebarProjectTree
const load = vi.fn()
const update = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
  owner.connection.set('local')
  load.mockResolvedValue(initial)
  vi.mocked(projectMemoryClient).mockResolvedValue({ load, update })
})
afterEach(cleanup)

async function openNotes() {
  render(<ProjectMemory project={project} />)
  fireEvent.click(screen.getByRole('button', { name: 'Project notes' }))
  await screen.findByText('Export PNG in A5.')
}

it('shows stored notes and saves corrections or deletes using the loaded revision', async () => {
  await openNotes()
  expect(screen.getByText(initial.path)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Open notes folder' }))
  expect(revealPath).toHaveBeenCalledWith(initial.path)
  fireEvent.click(screen.getByRole('button', { name: 'Edit note' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'Note' }), { target: { value: 'Export PNG in A4.' } })
  update.mockResolvedValueOnce({
    saved: true,
    conflict: false,
    error: null,
    memory: { ...initial, revision: 'two', entries: [{ id: 'a4', content: 'Export PNG in A4.' }] }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await screen.findByText('Export PNG in A4.')
  expect(update).toHaveBeenCalledWith({
    action: 'patch',
    note_id: 'png',
    content: 'Export PNG in A4.',
    revision: 'one'
  })
  update.mockResolvedValueOnce({
    saved: true,
    conflict: false,
    error: null,
    memory: { ...initial, revision: 'three', entries: [] }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Delete note' }))
  await screen.findByText('No saved notes for this project yet.')
  expect(update).toHaveBeenLastCalledWith({ action: 'remove', note_id: 'a4', content: undefined, revision: 'two' })
})

it('retains the draft and its old revision when another writer changes the notes', async () => {
  await openNotes()
  fireEvent.click(screen.getByRole('button', { name: 'Edit note' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'Note' }), { target: { value: 'My correction' } })
  update.mockResolvedValue({
    saved: false,
    conflict: true,
    error: 'Notes changed elsewhere.',
    memory: { ...initial, revision: 'newer' }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect((await screen.findByRole('alert')).textContent).toContain('Notes changed elsewhere.')
  expect((screen.getByRole('textbox', { name: 'Note' }) as HTMLTextAreaElement).value).toBe('My correction')
  expect(update).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(update).toHaveBeenCalledTimes(2))
  expect(update).toHaveBeenLastCalledWith(expect.objectContaining({ revision: 'one' }))
})

it('drops an in-flight read when the owning connection changes', async () => {
  const pending = deferred<typeof initial>()
  load.mockReturnValue(pending.promise)
  render(<ProjectMemory project={project} />)
  fireEvent.click(screen.getByRole('button', { name: 'Project notes' }))
  await waitFor(() => expect(load).toHaveBeenCalledOnce())
  owner.connection.set('remote')
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  pending.resolve(initial)
  await Promise.resolve()
  expect(screen.queryByText('Export PNG in A5.')).toBeNull()
  expect(screen.getByRole('button', { name: 'Project notes' })).toBeTruthy()
})
