import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { PersonalDevicesSettings } from './personal-devices-settings'

vi.mock('qrcode', () => ({ toDataURL: async () => 'data:image/png;base64,QR' }))
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('creates a named space then pairs another device to that same space and revokes only one', async () => {
  const space = { id: 'a'.repeat(32), name: 'Λάζαρος' }

  const devices: { id: string; space_id: string; label: string; paired: boolean; state: string; last_contact: null }[] =
    []

  const api = vi.fn(
    async ({ method, body, path }: { method?: string; body?: Record<string, string>; path: string }) => {
      if (method === 'POST') {
        const id = String(devices.length + 1)
        devices.push({
          id,
          space_id: space.id,
          label: body?.label || space.name,
          paired: false,
          state: 'waiting',
          last_contact: null
        })

        return { device_id: id, space_name: space.name, code: 'meusync2.fixture' }
      }

      if (method === 'DELETE') {
        const index = devices.findIndex(d => path.endsWith('/' + d.id))
        devices.splice(index, 1)
      }

      return { management_version: 2, spaces: [space], devices: devices.map(d => ({ ...d })) }
    }
  )

  vi.stubGlobal('hermesDesktop', { api })
  const view = render(<PersonalDevicesSettings profile="work" />)
  fireEvent.change(await screen.findByLabelText('Name / nickname'), { target: { value: 'Λάζαρος' } })
  fireEvent.change(screen.getByLabelText('Device name (optional)'), { target: { value: 'Κινητό 1' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add device · show QR' }))
  expect(await screen.findByRole('img', { name: 'Personal device pairing QR' })).toBeTruthy()
  expect(api).toHaveBeenCalledWith(
    expect.objectContaining({
      method: 'POST',
      profile: 'work',
      connectionId: 'local',
      body: { name: 'Λάζαρος', label: 'Κινητό 1', owner: false }
    })
  )
  // An application reopen reads the durable list; it never mints a second QR automatically.
  devices[0].paired = true
  devices[0].state = 'paired'
  view.unmount()
  render(<PersonalDevicesSettings profile="work" />)
  fireEvent.change(await screen.findByLabelText('Personal space'), { target: { value: space.id } })
  expect(screen.queryByLabelText('Name / nickname')).toBeNull()
  fireEvent.change(screen.getByLabelText('Device name (optional)'), { target: { value: 'Κινητό 2' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add device · show QR' }))
  await screen.findByRole('button', { name: 'Disconnect Κινητό 2' })
  expect(api).toHaveBeenCalledWith(
    expect.objectContaining({ method: 'POST', body: { space_id: space.id, label: 'Κινητό 2' } })
  )
  fireEvent.click(screen.getByRole('button', { name: 'Disconnect Κινητό 1' }))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Disconnect Κινητό 1' })).toBeNull())
  expect(screen.getByRole('button', { name: 'Disconnect Κινητό 2' })).toBeTruthy()
  expect(api).toHaveBeenCalledWith(
    expect.objectContaining({ method: 'DELETE', path: '/api/mobile-preview/devices/1', profile: 'work' })
  )
})

it('retains the user form after a refusal and never falls back to unrestricted pairing', async () => {
  const api = vi.fn(async ({ method }: { method?: string }) => {
    if (method === 'POST') {
      throw new Error('folder exists')
    }

    return { management_version: 2, spaces: [], devices: [] }
  })

  vi.stubGlobal('hermesDesktop', { api })
  render(<PersonalDevicesSettings />)
  fireEvent.change(await screen.findByLabelText('Name / nickname'), { target: { value: 'Existing' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add device · show QR' }))
  expect((await screen.findByRole('alert')).textContent).toContain('select an existing user')
  expect((screen.getByLabelText('Name / nickname') as HTMLInputElement).value).toBe('Existing')
  expect(
    api.mock.calls
      .filter(([args]) => args.method === 'POST')
      .every(([args]) => (args as { path?: string }).path === '/api/mobile-preview/devices')
  ).toBe(true)
})

it('requires an explicit owner choice before pairing a device to the PC workspace', async () => {
  const api = vi.fn(async ({ method }: { method?: string }) => {
    if (method === 'POST') return { device_id: 'owner-phone', space_name: 'Owner', code: 'meusync2.fixture' }
    return { management_version: 2, spaces: [], devices: [] }
  })
  vi.stubGlobal('hermesDesktop', { api })
  render(<PersonalDevicesSettings />)
  const owner = await screen.findByRole('checkbox', { name: 'This is my device · PC owner' })
  expect((owner as HTMLInputElement).checked).toBe(false)
  fireEvent.change(screen.getByLabelText('Name / nickname'), { target: { value: 'Owner' } })
  fireEvent.click(owner)
  fireEvent.click(screen.getByRole('button', { name: 'Add device · show QR' }))
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'POST',
        path: '/api/mobile-preview/devices',
        body: { name: 'Owner', owner: true }
      })
    )
  )
})
