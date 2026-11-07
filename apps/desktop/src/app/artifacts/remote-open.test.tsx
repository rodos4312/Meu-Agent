import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'

import { hermesApiAs } from '@/api/client'
import { $connection } from '@/store/session'

import { ArtifactsView } from './index'

const paths = vi.hoisted(() => [
  '~/.hermes/memories/USER.md',
  './report.md',
  '../parent.md',
  String.raw`~\home.txt`,
  String.raw`.\child.txt`,
  String.raw`..\ancestor.txt`,
  'file:///C:/output/drive.txt',
  'file://server/share/unc.txt',
  '/srv/absolute.txt'
])

const getSessionMessages = vi.hoisted(() => vi.fn())
vi.mock('@/api/client', async () => ({ ...(await vi.importActual('@/api/client')), hermesApiAs: vi.fn() }))
vi.mock('@/app/chat/right-rail/preview-file', () => ({ SourceView: ({ text }: { text: string }) => <pre>{text}</pre> }))

vi.mock('@/hermes', async () => ({
  ...(await vi.importActual('@/hermes')),
  listAllProfileSessions: async () => ({
    sessions: [{ id: 'artifact-session', title: 'Fixture', profile: 'origin-profile' }]
  }),
  getSessionMessages
}))
afterEach(() => {
  cleanup()
  $connection.set(null)
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

it('previews files in place and downloads only on request, preserving the originating owner and raw path', async () => {
  vi.mocked(hermesApiAs).mockResolvedValue({ path: '/fixture', text: 'Preview body' })
  getSessionMessages.mockResolvedValue({
    messages: [
      {
        role: 'assistant',
        timestamp: 1000,
        content: paths.map(path => `MEDIA:${path}`).join(' ') + ' https://example.com/report.txt'
      }
    ],
    session_id: 'artifact-session'
  })
  const saveGatewayFile = vi.fn().mockResolvedValue({ saved: true })
  const openExternal = vi.fn()
  vi.stubGlobal('hermesDesktop', { saveGatewayFile, openExternal })
  $connection.set({
    isFullscreen: false,
    nativeOverlayWidth: 0,
    logs: [],
    windowButtonPosition: null,
    mode: 'remote',
    connectionId: 'remote-fixture',
    profile: 'writer',
    baseUrl: 'http://localhost',
    token: '',
    wsUrl: ''
  })
  render(
    <MemoryRouter>
      <ArtifactsView />
    </MemoryRouter>
  )

  for (const name of [
    'USER.md',
    'report.md',
    'parent.md',
    'home.txt',
    'child.txt',
    'ancestor.txt',
    'drive.txt',
    'unc.txt',
    'absolute.txt'
  ]) {
    fireEvent.click(await screen.findByRole('button', { name }))
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByText('Preview body')
    expect(saveGatewayFile).toHaveBeenCalledTimes(paths.indexOf(paths.find(path => path.endsWith(name))!))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Download' }))
    await waitFor(() =>
      expect(saveGatewayFile).toHaveBeenCalledTimes(paths.indexOf(paths.find(path => path.endsWith(name))!) + 1)
    )
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
  }

  await waitFor(() => expect(saveGatewayFile).toHaveBeenCalledTimes(paths.length))
  expect(saveGatewayFile.mock.calls.map(([request]) => request)).toEqual(
    paths.map(path => ({
      connectionId: 'remote-fixture',
      profile: 'origin-profile',
      sessionId: 'artifact-session',
      path,
      suggestedName: path.split(/[\\/]/).pop()
    }))
  )
  expect(screen.getByRole('link').getAttribute('href')).toBe('https://example.com/report.txt')
  expect(openExternal).not.toHaveBeenCalled()
  expect(getSessionMessages).toHaveBeenCalledWith(
    'artifact-session',
    { connectionId: 'remote-fixture', profile: 'origin-profile' },
    {
      includeCompacted: true,
      limit: expect.any(Number),
      offset: 0,
      order: 'oldest'
    }
  )
})
