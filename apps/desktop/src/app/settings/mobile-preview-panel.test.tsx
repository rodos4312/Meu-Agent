import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { $apiRequestScope } from '@/api/client'
import { MobilePreviewPanel } from './mobile-preview-panel'

vi.mock('qrcode', () => ({ toDataURL: async () => 'data:image/png;base64,QR' }))
afterEach(() => {
  cleanup()
  $apiRequestScope.set({ connectionId: null, profile: null })
  vi.unstubAllGlobals()
})

function setup(failMigration = false) {
  let migrated = false
  const owner = { id: 'a'.repeat(32), name: 'Owner', owner: true }
  const api = vi.fn(async ({ path, method }: { path: string; method?: string }) => {
    if (path === '/api/meu-transfers') return { enabled: true, directory: 'C:/fixture/shared' }
    if (path.endsWith('/migrate') && method === 'POST') {
      if (failMigration) throw new Error('controlled refusal')
      migrated = true
      return { migrated: true, device_id: 'old-phone', space_id: owner.id, space_name: owner.name }
    }
    return {
      management_version: 2,
      spaces: migrated ? [owner] : [],
      devices: migrated
        ? [
            {
              id: 'old-phone',
              space_id: owner.id,
              label: 'Existing phone',
              paired: true,
              state: 'paired',
              last_contact: null
            }
          ]
        : [],
      legacy: migrated ? null : { state: 'paired', kind: 'profile', can_migrate: true }
    }
  })
  vi.stubGlobal('hermesDesktop', { api })
  $apiRequestScope.set({ connectionId: null, profile: 'work' })
  return api
}

it('offers one management surface and migrates the existing grant without re-pairing or deleting it', async () => {
  const api = setup()
  render(<MobilePreviewPanel />)
  await screen.findByRole('button', { name: 'Keep existing connection' })
  expect(screen.queryByRole('button', { name: 'Show pairing code' })).toBeNull()
  expect(screen.getAllByRole('heading', { name: 'Devices and sharing' })).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: 'Keep existing connection' }))
  fireEvent.change(screen.getByLabelText('Your name / nickname'), { target: { value: 'Owner' } })
  fireEvent.change(screen.getByLabelText('Existing device name (optional)'), { target: { value: 'Existing phone' } })
  fireEvent.click(screen.getByRole('button', { name: 'Finish migration' }))
  await screen.findByRole('button', { name: 'Disconnect Existing phone' })
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Keep existing connection' })).toBeNull())
  expect(api).toHaveBeenCalledWith(
    expect.objectContaining({
      method: 'POST',
      profile: 'work',
      path: '/api/mobile-preview/devices/migrate',
      body: { name: 'Owner', label: 'Existing phone' }
    })
  )
  expect(api.mock.calls.some(([args]) => args.method === 'DELETE')).toBe(false)
  expect(screen.queryByRole('img')).toBeNull()
  expect(screen.getByText('C:/fixture/shared')).toBeTruthy()
  expect((screen.getByLabelText('Personal space') as HTMLSelectElement).value).toBe('a'.repeat(32))
})

it('keeps the old connection and entered details visible after a refused migration', async () => {
  const api = setup(true)
  render(<MobilePreviewPanel />)
  fireEvent.click(await screen.findByRole('button', { name: 'Keep existing connection' }))
  fireEvent.change(screen.getByLabelText('Your name / nickname'), { target: { value: 'Owner' } })
  fireEvent.click(screen.getByRole('button', { name: 'Finish migration' }))
  expect((await screen.findByRole('alert')).textContent).toContain('conversations and files were kept')
  expect((screen.getByLabelText('Your name / nickname') as HTMLInputElement).value).toBe('Owner')
  expect(screen.getByRole('button', { name: 'Disconnect existing connection' })).toBeTruthy()
  expect(api.mock.calls.some(([args]) => args.method === 'DELETE')).toBe(false)
})

it('does not create or widen a grant when the backend lacks unified management', async () => {
  const api = vi.fn(async () => ({ spaces: [], devices: [] }))
  vi.stubGlobal('hermesDesktop', { api })
  render(<MobilePreviewPanel />)
  await screen.findByText('Update Meu on the PC to use unified device management.')
  expect(screen.queryByRole('button', { name: 'Add device · show QR' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Show pairing code' })).toBeNull()
})
