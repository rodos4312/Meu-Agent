import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { I18nProvider } from '@/i18n/context'
import { en } from '@/i18n/en'
import {
  $backendUpdateApply,
  $updateApply,
  $updateOverlayOpen,
  $updateOverlayTarget,
  $updateStatus,
  applyUpdates,
  resetUpdateApplyState
} from '@/store/updates'

import { UpdatesOverlay } from './updates-overlay'

it.each(['client', 'backend'] as const)(
  'offers a trusted installer download only for a failed Meu %s update',
  async target => {
    const openExternal = vi.fn(async () => undefined)
    window.hermesDesktop = { openExternal } as unknown as Window['hermesDesktop']
    $updateOverlayTarget.set(target)
    $updateOverlayOpen.set(true)
    $updateStatus.set({
      supported: true,
      channel: 'meu-preview',
      mechanism: 'electron-updater',
      updateAvailable: true,
      fetchedAt: 1
    })
    const state = target === 'backend' ? $backendUpdateApply : $updateApply
    state.set({ ...state.get(), applying: false, stage: 'error', message: 'Use the latest Meu installer.' })
    await act(async () => {
      render(
        <I18nProvider configClient={null} initialLocale="en">
          <UpdatesOverlay />
        </I18nProvider>
      )
    })
    expect(openExternal).not.toHaveBeenCalled()

    if (target === 'client') {
      const download = screen.getByRole('link', { name: en.updates.openDownloadPage })
      expect(download.getAttribute('href')).toBe('https://github.com/rodos4312/Meu-Agent/releases')
      fireEvent.click(download)
      expect(openExternal).toHaveBeenCalledWith('https://github.com/rodos4312/Meu-Agent/releases')
    } else {
      expect(screen.queryByRole('link', { name: en.updates.openDownloadPage })).toBeNull()
    }
  }
)

afterEach((): void => {
  cleanup()
  $updateOverlayOpen.set(false)
  $updateStatus.set(null)
  resetUpdateApplyState()
  Reflect.deleteProperty(window, 'hermesDesktop')
  vi.restoreAllMocks()
})

it('shows manual recovery guidance without claiming the help command installs an update', async (): Promise<void> => {
  const message: string = 'Choose the intended branch or channel before updating this older checkout.'
  window.hermesDesktop = {
    updates: {
      apply: async (): Promise<unknown> => ({ ok: true, manual: true, command: 'hermes update --help', message })
    }
  } as unknown as Window['hermesDesktop']
  $updateOverlayTarget.set('client')
  $updateOverlayOpen.set(true)
  $updateStatus.set({ supported: false, reason: 'source-probe-unavailable', message })
  await applyUpdates()
  expect($updateApply.get().message).toBe(message)
  await act(async (): Promise<void> => {
    render(
      <I18nProvider configClient={null} initialLocale="en">
        <UpdatesOverlay />
      </I18nProvider>
    )
  })
  expect(screen.getByText(message)).toBeTruthy()
  expect(screen.getByText('hermes update --help')).toBeTruthy()
  expect(screen.queryByText(en.updates.manualPickedUp)).toBeNull()
})

it('titles a command-less backend refusal honestly and offers nothing to copy', async (): Promise<void> => {
  const message: string = 'Hermes updates are managed outside this dashboard in containerized environments.'
  $updateOverlayTarget.set('backend')
  $updateOverlayOpen.set(true)
  $backendUpdateApply.set({
    applying: false,
    stage: 'manual',
    message,
    percent: null,
    error: null,
    command: null,
    log: []
  })
  await act(async (): Promise<void> => {
    render(
      <I18nProvider configClient={null} initialLocale="en">
        <UpdatesOverlay />
      </I18nProvider>
    )
  })
  expect(screen.getByText(en.updates.manualUnavailableTitle)).toBeTruthy()
  expect(screen.queryByText(en.updates.manualTitle)).toBeNull()
  expect(screen.getByText(message)).toBeTruthy()
  expect(screen.queryByText(en.updates.copy)).toBeNull()
})

it('names the backend, not a local install, when a remote refusal carries a bare command', async (): Promise<void> => {
  $updateOverlayTarget.set('backend')
  $updateOverlayOpen.set(true)
  $backendUpdateApply.set({
    applying: false,
    stage: 'manual',
    message: '',
    percent: null,
    error: null,
    command: 'docker pull nousresearch/hermes-agent:latest',
    log: []
  })
  await act(async (): Promise<void> => {
    render(
      <I18nProvider configClient={null} initialLocale="en">
        <UpdatesOverlay />
      </I18nProvider>
    )
  })
  expect(screen.getByText('docker pull nousresearch/hermes-agent:latest')).toBeTruthy()
  expect(screen.getByText(en.updates.manualBodyBackend)).toBeTruthy()
  expect(screen.getByText(en.updates.manualPickedUpBackend)).toBeTruthy()
  expect(screen.queryByText(en.updates.manualBody)).toBeNull()
})

it('keeps the client title for a command-less client manual stage', async (): Promise<void> => {
  $updateOverlayTarget.set('client')
  $updateOverlayOpen.set(true)
  $updateApply.set({
    applying: false,
    stage: 'manual',
    message: 'Hermes will pick up the new version next time you launch it.',
    percent: null,
    error: null,
    command: null,
    log: []
  })
  await act(async (): Promise<void> => {
    render(
      <I18nProvider configClient={null} initialLocale="en">
        <UpdatesOverlay />
      </I18nProvider>
    )
  })
  expect(screen.getByText(en.updates.manualTitle)).toBeTruthy()
  expect(screen.queryByText(en.updates.manualUnavailableTitle)).toBeNull()
})
