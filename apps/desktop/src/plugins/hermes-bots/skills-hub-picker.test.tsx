/** Skill search and installation use the backend, without a hosted frame. */

import type * as HermesSdk from '@hermes/plugin-sdk'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { translateBots } from './i18n-test-helper'


const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  notifyError: vi.fn(),
  request: vi.fn(async (_method: string, _params: Record<string, unknown>): Promise<any> => ({})),
  requestProfile: vi.fn(async (_route: unknown, _method: string, _params: Record<string, unknown>) => ({}))
}))

vi.mock('@hermes/plugin-sdk', async importOriginal => {
  const original = await importOriginal<typeof HermesSdk>()

  return {
    ...original,
    usePluginI18n: () => translateBots,
    host: {
      ...original.host,
      notify: mocks.notify,
      notifyError: mocks.notifyError,
      request: mocks.request,
      requestProfile: mocks.requestProfile
    }
  }
})

const { HubSkillsSection } = await import('./skills-hub')


afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks() })

it('searches and installs skills without loading a hosted frame', async () => {
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  mocks.request.mockResolvedValue({ results: [{ name: 'weather', description: 'Weather skill' }] })
  const { container } = render(<HubSkillsSection />)
  expect(container.querySelector('iframe')).toBeNull()
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'weather' } })
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' })
  await screen.findByText('Weather skill')
  fireEvent.click(screen.getByRole('button', { name: /weather/i }))
  await waitFor(() => expect(mocks.request).toHaveBeenCalledWith('skills.manage', { action: 'install', query: 'weather' }))
  expect(fetch).not.toHaveBeenCalled()
})
