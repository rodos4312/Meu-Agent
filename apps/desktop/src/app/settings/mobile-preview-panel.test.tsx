import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { $apiRequestScope } from '@/api/client'

import { MobilePreviewPanel } from './mobile-preview-panel'

vi.mock('qrcode', () => ({ toDataURL: async () => 'data:image/png;base64,QR' }))

afterEach(() => {
  cleanup()
  $apiRequestScope.set({ connectionId: null, profile: null })
  vi.unstubAllGlobals()
})

it('shows the local profile QR after an explicit start and clears it on disconnect', async () => {
  let state: { state: string; code?: string; seconds?: number } = { state: 'off' }

  const api = vi.fn(async ({ method }: { method?: string }) => {
    if (method === 'POST') {
      state = { state: 'waiting', code: 'meu2.test', seconds: 300 }
    }

    if (method === 'DELETE') {
      state = { state: 'off' }
    }

    return state
  })

  $apiRequestScope.set({ connectionId: null, profile: 'work' })
  vi.stubGlobal('hermesDesktop', { api })
  render(<MobilePreviewPanel />)

  expect(screen.queryByRole('img')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Show pairing code' }))
  expect(await screen.findByRole('img', { name: 'Meu pairing QR code' })).toBeTruthy()
  expect(api).toHaveBeenCalledWith(expect.objectContaining({
    method: 'POST', path: '/api/mobile-preview', connectionId: 'local', profile: 'work'
  }))

  fireEvent.click(screen.getByRole('button', { name: 'Disconnect phone' }))
  await screen.findByRole('button', { name: 'Show pairing code' })
  expect(screen.queryByRole('img')).toBeNull()
  expect(api).toHaveBeenCalledWith(expect.objectContaining({ method: 'DELETE', connectionId: 'local', profile: 'work' }))
})

it('requests remote pairing only when selected and leaves the user a retry path', async () => {
  let state: { state: string; code?: string; seconds?: number } = { state: 'off' }

  const api = vi.fn(async ({ path, method }: { path: string; method?: string }) => {
    if (method === 'POST') {
      if (path.endsWith('/internet')) {
        throw new Error('Meu relay unavailable')
      }

      state = { state: 'waiting', code: 'meu2.test', seconds: 300 }
    }

    return state
  })

  vi.stubGlobal('hermesDesktop', { api })
  render(<MobilePreviewPanel />)

  const remote = screen.getByRole('checkbox', { name: 'Connect from outside home' })
  fireEvent.click(remote)
  fireEvent.click(screen.getByRole('button', { name: 'Show pairing code' }))
  expect((await screen.findByRole('alert')).textContent).toContain('Could not start internet pairing')
  expect(api).toHaveBeenCalledWith(expect.objectContaining({
    method: 'POST', path: '/api/mobile-preview/internet', connectionId: 'local'
  }))
  expect(screen.queryByRole('img')).toBeNull()

  fireEvent.click(remote)
  fireEvent.click(screen.getByRole('button', { name: 'Show pairing code' }))
  expect(await screen.findByRole('img', { name: 'Meu pairing QR code' })).toBeTruthy()
})

it('shares only the explicitly selected local conversation in sync mode', async () => {
  const sessionId = 'local-' + 'a'.repeat(64)
  const api = vi.fn(async ({ method, path }: { method?: string; path: string }) => {
    if (path.startsWith('/api/sessions?')) {
      return { sessions: [{ id: sessionId, title: 'Trip plans' }] }
    }

    if (method === 'POST') {
      return { state: 'waiting', code: 'meusync1.test', seconds: 300, sync: true }
    }

    return { state: 'off' }
  })

  $apiRequestScope.set({ connectionId: null, profile: 'work' })
  vi.stubGlobal('hermesDesktop', { api })
  render(<MobilePreviewPanel />)

  fireEvent.click(screen.getByRole('checkbox', { name: 'Sync conversation history via Wi-Fi or Tailscale' }))
  const button = screen.getByRole('button', { name: 'Show pairing code' })
  expect((button as HTMLButtonElement).disabled).toBe(true)
  await screen.findByRole('option', { name: 'Trip plans' })
  fireEvent.change(screen.getByRole('combobox', { name: 'Conversation to share' }), {
    target: { value: sessionId }
  })
  fireEvent.click(button)
  expect(await screen.findByRole('img', { name: 'Meu pairing QR code' })).toBeTruthy()
  expect(api).toHaveBeenCalledWith(expect.objectContaining({
    method: 'POST', path: '/api/mobile-preview/sync', connectionId: 'local',
    profile: 'work', body: { session_id: sessionId }
  }))
})
