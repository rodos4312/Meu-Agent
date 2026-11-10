import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { ProjectSyncSettings } from './project-sync-settings'

const api = vi.hoisted(() => vi.fn())
vi.mock('@/api/client', () => ({ hermesApi: api }))
vi.mock('@/i18n/context', () => ({ useI18n: () => ({ locale: 'en' }) }))
afterEach(() => { cleanup(); api.mockReset(); vi.unstubAllGlobals() })

it('links the selected folder and conversation in the owning profile', async () => {
  api.mockResolvedValue({ projects: [], conversations: [{ id: 'chat-one', title: 'Build game' }] })
  const selectPaths = vi.fn(async () => ['C:/projects/Game'])
  vi.stubGlobal('hermesDesktop', { selectPaths })
  render(<ProjectSyncSettings profile="work" />)
  await screen.findByRole('option', { name: 'Build game' })
  fireEvent.change(screen.getByLabelText('Project conversation'), { target: { value: 'chat-one' } })
  fireEvent.click(screen.getByRole('button', { name: 'Choose project folder' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith(expect.objectContaining({
    profile: 'work', path: '/api/mobile-preview/projects', method: 'POST',
    body: { directory: 'C:/projects/Game', name: 'Game', session_id: 'chat-one' }
  })))
})
