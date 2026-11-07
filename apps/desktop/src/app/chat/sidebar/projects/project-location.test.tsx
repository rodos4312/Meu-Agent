import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { atom } from 'nanostores'
import { afterEach, expect, it, vi } from 'vitest'

import type * as DesktopFs from '@/lib/desktop-fs'
import type * as ProjectsStore from '@/store/projects'
import { copyPath, revealPath } from '@/store/projects'

import { ProjectLocation } from './project-location'
import type { SidebarProjectTree } from './workspace-groups'

const owner = vi.hoisted(() => ({ connection: null as unknown as ReturnType<typeof atom<string>> }))
vi.mock('@/store/connections', async () => {
  const { atom } = await import('nanostores')
  owner.connection = atom('local')

  return { $activeConnectionId: owner.connection }
})
vi.mock('@/store/projects', async importOriginal => ({
  ...(await importOriginal<typeof ProjectsStore>()),
  copyPath: vi.fn(),
  revealPath: vi.fn()
}))
vi.mock('@/lib/desktop-fs', async importOriginal => ({
  ...(await importOriginal<typeof DesktopFs>()),
  isDesktopFsRemoteMode: () => false
}))

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

const path = 'C:\\Users\\Demo\\Meu Projects\\Birthday card'
const project: SidebarProjectTree = { id: 'p_demo', label: 'Birthday card', path, repos: [], sessionCount: 0 }

it('copies and opens the exact backend path, retaining spaces and Windows separators', () => {
  owner.connection.set('local')
  render(<ProjectLocation project={project} />)
  expect(screen.getByTitle(path)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Copy path' }))
  expect(copyPath).toHaveBeenCalledWith(path)
  fireEvent.click(screen.getByRole('button', { name: 'Reveal in folder' }))
  expect(revealPath).toHaveBeenCalledWith(path)
})

it('remote folders remain copyable without opening the same path on this computer', () => {
  owner.connection.set('remote-device')
  render(<ProjectLocation project={{ ...project, path: '/work/meu/tasks' }} />)
  fireEvent.click(screen.getByRole('button', { name: 'Copy path' }))
  expect(copyPath).toHaveBeenCalledWith('/work/meu/tasks')
  expect(screen.queryByRole('button', { name: 'Reveal in folder' })).toBeNull()
  expect(revealPath).not.toHaveBeenCalled()
})

it('does not invent a storage path for the Home bucket', () => {
  const { container } = render(<ProjectLocation project={{ ...project, isNoProject: true, path: null }} />)
  expect(container.textContent).toBe('')
})
