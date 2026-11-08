import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { TransferFolderSettings } from './transfer-folder-settings'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('selects and revokes one local folder with the existing owner scope', async () => {
  let directory = ''
  const api = vi.fn(async request => {
    expect(request.connectionId).toBe('local')
    expect(request.profile).toBe('work')
    if (request.method === 'POST') directory = request.body.directory
    return { enabled: !!directory, directory }
  })
  const selectPaths = vi.fn(async () => ['C:\\Meu Transfers'])
  vi.stubGlobal('hermesDesktop', { api, selectPaths })
  render(<TransferFolderSettings profile="work" />)
  const choose = await screen.findByRole('button', { name: 'Choose folder' })
  await waitFor(() => expect((choose as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(choose)
  expect(await screen.findByText('C:\\Meu Transfers')).toBeTruthy()
  expect(selectPaths).toHaveBeenCalledWith({ directories: true, multiple: false })
  fireEvent.click(screen.getByRole('button', { name: 'Stop sharing' }))
  expect(await screen.findByText('No folder selected.')).toBeTruthy()
  expect(api).toHaveBeenCalledWith(
    expect.objectContaining({ path: '/api/meu-transfers/folder', body: { directory: '' } })
  )
  expect(api.mock.calls.every(([request]) => request.path.startsWith('/api/meu-transfers'))).toBe(true)
})

it('does not let a late previous-profile read replace the selected profile folder', async () => {
  let finish: (value: unknown) => void = () => {}
  const old = new Promise(resolve => {
    finish = resolve
  })
  vi.stubGlobal('hermesDesktop', {
    api: vi.fn(({ profile }) =>
      profile === 'old' ? old : Promise.resolve({ enabled: true, directory: 'Current profile folder' })
    )
  })
  const view = render(<TransferFolderSettings profile="old" />)
  view.rerender(<TransferFolderSettings profile="current" />)
  expect(await screen.findByText('Current profile folder')).toBeTruthy()
  finish({ enabled: true, directory: 'Old private folder' })
  await waitFor(() => expect(screen.queryByText('Old private folder')).toBeNull())
})
