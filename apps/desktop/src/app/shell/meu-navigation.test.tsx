import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { MemoryRouter, useLocation } from 'react-router'
import { afterEach, expect, it } from 'vitest'

import { I18nProvider } from '@/i18n'

import { MeuCapabilitySidebar, MeuNavigationRail } from './meu-navigation'

function SessionProbe() {
  const location = useLocation()
  const [draft, setDraft] = useState('')

  return (
    <>
      <output data-testid="route">
        {location.pathname}
        {location.search}
        {location.hash}
      </output>
      <input aria-label="Draft" onChange={event => setDraft(event.target.value)} value={draft} />
    </>
  )
}

function fixture(path = '/existing-chat?view=full#message') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <I18nProvider configClient={null} initialLocale="en">
        <MeuNavigationRail />
        <MeuCapabilitySidebar />
        <SessionProbe />
      </I18nProvider>
    </MemoryRouter>
  )
}

afterEach(cleanup)

it('returns Home to the existing chat with its draft after visiting pages and overlays', () => {
  fixture()
  fireEvent.change(screen.getByLabelText('Draft'), { target: { value: 'Unsent message' } })

  for (const [name, path] of [
    ['Plugins', '/capabilities?tab=plugins'],
    ['Scheduled jobs', '/cron'],
    ['Settings', '/settings']
  ] as const) {
    fireEvent.click(
      screen.getByRole('navigation', { name: 'Main navigation' }).querySelector(`[aria-label="${name}"]`)!
    )
    expect(screen.getByTestId('route').textContent).toBe(path)
  }

  fireEvent.click(screen.getByRole('button', { name: 'Home' }))
  expect(screen.getByTestId('route').textContent).toBe('/existing-chat?view=full#message')
  expect((screen.getByLabelText('Draft') as HTMLInputElement).value).toBe('Unsent message')
})

it('keeps the customization menu and direct rail routes in agreement', () => {
  fixture('/')
  const menu = screen.getByRole('navigation', { name: 'Customize' })
  fireEvent.click(menu.querySelector('button')!)
  expect(screen.getByTestId('route').textContent).toBe('/capabilities?tab=plugins')
  expect(menu.querySelector('[aria-current="page"]')?.textContent).toBe('Plugins')
  fireEvent.click(screen.getByRole('navigation', { name: 'Main navigation' }).querySelector('[data-meu-nav="skills"]')!)
  expect(screen.getByTestId('route').textContent).toBe('/capabilities?tab=skills')
  expect(menu.querySelector('[aria-current="page"]')?.textContent).toBe('Skills')
})
